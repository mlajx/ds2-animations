// Stuttering fix for DS2 SotFS, ported from ../SteamFixAlternative/src/ds2_fix_rootcause.cpp.
//
// Root cause (static analysis of DarkSoulsII.exe):
//   death -> UnlockAchievement(4) (+248690) -> CSteamAchievements::SetAchievement (+B5EAB0)
//         -> ISteamUserStats::SetAchievement + StoreStats, every death, even when already unlocked
//   UserStatsStored_t   (+B5E920) -> RequestCurrentStats
//   UserStatsReceived_t (+B5E6A0) -> 38 x (GetAchievement + 2 x GetAchievementDisplayAttribute)
//   re-init (+B26F00) frees the old CSteamAchievements without its destructor, so its three
//   SteamAPI_RegisterCallback registrations are never removed: each re-init adds another set.
//
// This fix keeps everything on the game thread and removes the work instead of moving it:
//   1. SetAchievement for an achievement that is already unlocked -> skipped, and the
//      StoreStats that follows it is skipped too (nothing changed, so nothing to store).
//   2. RequestCurrentStats -> at most once every 5 seconds (the received handler is the heavy part).
//   3. SteamAPI_RegisterCallback with the same object and callback ID twice -> registered once.
// New achievements still unlock and are stored normally.
#include "common.h"

// ---------------------------------------------------------------- ISteamUserStats (vtable indices, v011/v012)
// 0 RequestCurrentStats, 6 GetAchievement, 7 SetAchievement, 10 StoreStats
typedef bool (*RequestCurrentStats_t)(void*);
typedef bool (*GetAchievement_t)(void*, const char*, bool*);
typedef bool (*SetAchievement_t)(void*, const char*);
typedef bool (*StoreStats_t)(void*);
static RequestCurrentStats_t Original_RequestCurrentStats = nullptr;
static GetAchievement_t Original_GetAchievement = nullptr;
static SetAchievement_t Original_SetAchievement = nullptr;
static StoreStats_t Original_StoreStats = nullptr;

static volatile LONG g_skipNextStore = 0;
static volatile LONG g_pendingChange = 0;
static volatile LONG g_lastRequestTick = 0;

static bool Hooked_SetAchievement(void* stats, const char* name) {
    bool achieved = false;
    if (Original_GetAchievement && Original_GetAchievement(stats, name, &achieved) && achieved) {
        if (!g_pendingChange) InterlockedExchange(&g_skipNextStore, 1);
        return true;
    }
    InterlockedExchange(&g_skipNextStore, 0);
    InterlockedExchange(&g_pendingChange, 1);
    return Original_SetAchievement(stats, name);
}

static bool Hooked_StoreStats(void* stats) {
    if (InterlockedExchange(&g_skipNextStore, 0) && !g_pendingChange) return true;
    InterlockedExchange(&g_pendingChange, 0);
    return Original_StoreStats(stats);
}

static bool Hooked_RequestCurrentStats(void* stats) {
    LONG now = (LONG)GetTickCount();
    LONG last = g_lastRequestTick;
    if (last != 0 && now - last < 5000) return true;
    InterlockedExchange(&g_lastRequestTick, now);
    return Original_RequestCurrentStats(stats);
}

// ---------------------------------------------------------------- SteamAPI_RegisterCallback (import of DarkSoulsII.exe)
// CCallbackBase: +0 vtable, +8 uint8 flags (1 = registered), +C int callback id
typedef void (*RegisterCallback_t)(void*, int);
static RegisterCallback_t Original_RegisterCallback = nullptr;

struct Registration { void* object; int id; };
static Registration g_registrations[256];
static volatile LONG g_registrationCount = 0;

static void Hooked_RegisterCallback(void* callback, int id) {
    LONG n = g_registrationCount;
    for (LONG i = 0; i < n && i < 256; ++i) {
        if (g_registrations[i].object == callback && g_registrations[i].id == id) {
            // already in Steam's list: just restore the state the constructor cleared
            *((unsigned char*)callback + 8) |= 1;
            *(int*)((unsigned char*)callback + 0xC) = id;
            return;
        }
    }
    LONG slot = InterlockedIncrement(&g_registrationCount) - 1;
    if (slot < 256) {
        g_registrations[slot].object = callback;
        g_registrations[slot].id = id;
    }
    Original_RegisterCallback(callback, id);
}

static DWORD WINAPI InstallSteamHook(LPVOID) {
    HMODULE hSteamApi = nullptr;
    while (!hSteamApi) {
        hSteamApi = GetModuleHandleA("steam_api64.dll");
        Sleep(500);
    }

    typedef void* (*SteamUserStatsFn)();
    SteamUserStatsFn getSteamUserStats = (SteamUserStatsFn)GetProcAddress(hSteamApi, "SteamUserStats");

    if (getSteamUserStats) {
        void* statsInterface = nullptr;
        while (!statsInterface) {
            statsInterface = getSteamUserStats();
            Sleep(500);
        }

        uintptr_t* vtable = *(uintptr_t**)statsInterface;
        Original_GetAchievement = (GetAchievement_t)vtable[6];
        PatchSlot(&vtable[0], (void*)&Hooked_RequestCurrentStats, (void**)&Original_RequestCurrentStats);
        PatchSlot(&vtable[7], (void*)&Hooked_SetAchievement, (void**)&Original_SetAchievement);
        PatchSlot(&vtable[10], (void*)&Hooked_StoreStats, (void**)&Original_StoreStats);
        Log("steamfix: ISteamUserStats hooks installed");
    }
    return 0;
}

// Called from DllMain: before the game creates CSteamAchievements (its constructor registers the callbacks).
void SteamFix_Install() {
    if (uintptr_t* slot = FindImport(GetModuleHandleA(nullptr), "steam_api64.dll", "SteamAPI_RegisterCallback")) {
        PatchSlot(slot, (void*)&Hooked_RegisterCallback, (void**)&Original_RegisterCallback);
        Log("steamfix: SteamAPI_RegisterCallback deduplicated (IAT)");
    }
    CreateThread(nullptr, 0, InstallSteamHook, nullptr, 0, nullptr);
}
