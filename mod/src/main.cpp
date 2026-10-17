// DS2AnimMod: drop-in dinput8.dll for DS2 SotFS.
//   [SteamFix]   stuttering fix from SteamFixAlternative (on by default)
//   [AnimLoader] replaces archived game files with loose files from the mod folder
// Settings: DS2AnimMod.ini next to DarkSoulsII.exe. Log: DS2AnimMod.log.
#include "common.h"
#include "stdarg.h"
#include "stdio.h"
#include "string.h"

static wchar_t g_gameDir[MAX_PATH];
static wchar_t g_logPath[MAX_PATH];
static bool g_logEnabled = true;
static CRITICAL_SECTION g_logLock;

void Log(const char* format, ...) {
    if (!g_logEnabled) return;
    char line[1024];
    SYSTEMTIME t;
    GetLocalTime(&t);
    int n = snprintf(line, sizeof(line), "%02d:%02d:%02d.%03d  ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list args;
    va_start(args, format);
    n += vsnprintf(line + n, sizeof(line) - n - 2, format, args);
    va_end(args);
    if (n > (int)sizeof(line) - 2) n = sizeof(line) - 2;
    line[n++] = '\r';
    line[n++] = '\n';
    EnterCriticalSection(&g_logLock);
    HANDLE f = CreateFileW(g_logPath, FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_ALWAYS, 0, nullptr);
    if (f != INVALID_HANDLE_VALUE) {
        DWORD written;
        WriteFile(f, line, n, &written, nullptr);
        CloseHandle(f);
    }
    LeaveCriticalSection(&g_logLock);
}

void PatchSlot(uintptr_t* slot, void* hook, void** original) {
    DWORD oldProtect;
    VirtualProtect(slot, sizeof(uintptr_t), PAGE_EXECUTE_READWRITE, &oldProtect);
    *original = (void*)*slot;
    *slot = (uintptr_t)hook;
    VirtualProtect(slot, sizeof(uintptr_t), oldProtect, &oldProtect);
}

uintptr_t* FindImport(HMODULE module, const char* dllName, const char* functionName) {
    unsigned char* base = (unsigned char*)module;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return nullptr;
    for (IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + dir.VirtualAddress); imp->Name; ++imp) {
        if (_stricmp((const char*)(base + imp->Name), dllName) != 0) continue;
        IMAGE_THUNK_DATA* names = (IMAGE_THUNK_DATA*)(base + (imp->OriginalFirstThunk ? imp->OriginalFirstThunk : imp->FirstThunk));
        IMAGE_THUNK_DATA* iat = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++iat) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            IMAGE_IMPORT_BY_NAME* byName = (IMAGE_IMPORT_BY_NAME*)(base + names->u1.AddressOfData);
            if (strcmp((const char*)byName->Name, functionName) == 0) return (uintptr_t*)&iat->u1.Function;
        }
    }
    return nullptr;
}

// ---------------------------------------------------------------- dinput8 proxy
typedef HRESULT(WINAPI *DirectInput8Create_t)(HINSTANCE, DWORD, REFIID, LPVOID*, LPUNKNOWN);
static DirectInput8Create_t Real_DirectInput8Create = nullptr;

extern "C" __declspec(dllexport) HRESULT WINAPI DirectInput8Create(HINSTANCE hinst, DWORD dwVersion, REFIID riidltf, LPVOID* ppvOut, LPUNKNOWN punkOuter) {
    if (!Real_DirectInput8Create) {
        char systemFolderPath[MAX_PATH];
        GetSystemDirectoryA(systemFolderPath, MAX_PATH);
        strcat(systemFolderPath, "\\dinput8.dll");
        HMODULE realLibrary = LoadLibraryA(systemFolderPath);
        Real_DirectInput8Create = (DirectInput8Create_t)GetProcAddress(realLibrary, "DirectInput8Create");
    }
    return Real_DirectInput8Create(hinst, dwVersion, riidltf, ppvOut, punkOuter);
}

static void Startup() {
    GetModuleFileNameW(nullptr, g_gameDir, MAX_PATH);
    if (wchar_t* slash = wcsrchr(g_gameDir, L'\\')) *slash = 0;
    wchar_t ini[MAX_PATH];
    swprintf(ini, MAX_PATH, L"%ls\\DS2AnimMod.ini", g_gameDir);
    swprintf(g_logPath, MAX_PATH, L"%ls\\DS2AnimMod.log", g_gameDir);
    g_logEnabled = GetPrivateProfileIntW(L"General", L"Log", 1, ini) != 0;
    DeleteFileW(g_logPath);
    Log("DS2AnimMod starting (%ls)", g_gameDir);

    if (GetPrivateProfileIntW(L"SteamFix", L"Enabled", 1, ini))
        SteamFix_Install();
    else
        Log("steamfix: disabled in ini");

    if (GetPrivateProfileIntW(L"AnimLoader", L"Enabled", 1, ini)) {
        wchar_t folder[MAX_PATH], path[MAX_PATH];
        GetPrivateProfileStringW(L"AnimLoader", L"Folder", L"DS2AnimMod", folder, MAX_PATH, ini);
        swprintf(path, MAX_PATH, L"%ls\\%ls", g_gameDir, folder);
        AnimLoader_Install(path);
    } else {
        Log("loader: disabled in ini");
    }
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reasonForCall, LPVOID) {
    if (reasonForCall == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        InitializeCriticalSection(&g_logLock);
        Startup();
    }
    return TRUE;
}
