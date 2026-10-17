// Loose-file overrides for files inside the encrypted archives (GameDataEbl.bdt etc).
//
// How DarkSoulsII.exe reads an archived file (static analysis, see ../../tools):
//   DLEBL::DLEncryptedBinderLightFileDevice vtable[1] = open(this, const std::wstring* path, ...)
//     -> lookup(+FEF650): skip to after ':' in "gamedata:/morpheme4/chr/c0001.anibnd.dcx",
//        hash = hash * 37 + lower(c) ('\' -> '/'), then search the decrypted BHD5 kept in memory:
//        [dev+C0] BHD5 base, [dev+C8] bucket count, [dev+D0] buckets {u32 count, u32 offset}
//        entry (0x20): u32 hash, i32 size, i64 offset, i64 saltedHashOffset, i64 aesKeyOffset
//     -> a file operator reads entry.size bytes at entry.offset of the .bdt through
//        DLIOD::MicrosoftDiskFileOperator: SetFilePointer + ReadFile, or ReadFile(OVERLAPPED)
//        + GetOverlappedResult. Absolute seeks are clamped to the size the operator got from
//        GetFileInformationByHandle.
//
// Override: on the first open through each archive device, entries whose path has a file in
// the mod folder are pointed at a virtual offset past the end of the .bdt (unencrypted, no
// hash check). The exe's imports are hooked so .bdt handles report a size that covers the
// virtual range, and reads inside it are served from the loose file.
#include "common.h"
#include "string.h"
#include "wchar.h"
#include <string>
#include <vector>

static const uint64_t kVirtualBase = 0x4000000000ull;   // 256 GiB, far past any .bdt
static const uint64_t kVirtualStride = 0x100000000ull;  // 4 GiB per override

struct Override {
    std::wstring archivePath;   // "/morpheme4/chr/c0001.anibnd.dcx"
    uint32_t hash;
    std::vector<unsigned char> data;
    uint64_t virtualOffset;
    bool applied;
    volatile LONG served;
};

static std::vector<Override> g_overrides;
static SRWLOCK g_lock = SRWLOCK_INIT;

static uint32_t ArchiveHash(const wchar_t* path) {
    uint32_t hash = 0;
    for (; *path; ++path) {
        uint32_t c = *path;
        if (c >= 'A' && c <= 'Z') c += 0x20;
        else if (c == '\\') c = '/';
        hash = hash * 37 + c;
    }
    return hash;
}

// ---------------------------------------------------------------- mod folder scan
static void ScanFolder(const std::wstring& root, const std::wstring& relative) {
    WIN32_FIND_DATAW fd;
    HANDLE find = FindFirstFileW((root + relative + L"\\*").c_str(), &fd);
    if (find == INVALID_HANDLE_VALUE) return;
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
        std::wstring rel = relative + L"\\" + fd.cFileName;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            ScanFolder(root, rel);
            continue;
        }
        HANDLE file = CreateFileW((root + rel).c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        if (file == INVALID_HANDLE_VALUE) continue;
        Override o;
        o.data.resize(fd.nFileSizeLow);
        DWORD got = 0;
        bool ok = fd.nFileSizeHigh == 0 && ReadFile(file, o.data.data(), fd.nFileSizeLow, &got, nullptr) && got == fd.nFileSizeLow;
        CloseHandle(file);
        if (!ok) {
            Log("loader: could not read %ls", rel.c_str());
            continue;
        }
        o.archivePath = rel;
        for (wchar_t& c : o.archivePath) if (c == L'\\') c = L'/';
        o.hash = ArchiveHash(o.archivePath.c_str());
        o.virtualOffset = kVirtualBase + kVirtualStride * g_overrides.size();
        o.applied = false;
        o.served = 0;
        Log("loader: override %ls (%u bytes, hash %08x)", o.archivePath.c_str(), (unsigned)o.data.size(), o.hash);
        g_overrides.push_back(std::move(o));
    } while (FindNextFileW(find, &fd));
    FindClose(find);
}

// ---------------------------------------------------------------- archive device: entry patching
struct BhdEntry {
    uint32_t hash;
    int32_t size;
    int64_t offset;
    int64_t saltedHashOffset;
    int64_t aesKeyOffset;
};

typedef void* (*EblOpen_t)(void*, void*, void*, void*, void*, unsigned char);
static EblOpen_t Original_EblOpen = nullptr;
static void* g_patchedDevices[32];
static int g_patchedDeviceCount = 0;

static void PatchDevice(unsigned char* device) {
    unsigned char* base = *(unsigned char**)(device + 0xC0);
    uint32_t bucketCount = *(uint32_t*)(device + 0xC8);
    uint32_t* buckets = *(uint32_t**)(device + 0xD0);
    if (!base || !bucketCount || !buckets || memcmp(base, "BHD5", 4) != 0) {
        Log("loader: device %p has no BHD5 table, skipped", device);
        return;
    }
    for (Override& o : g_overrides) {
        uint32_t bucket = o.hash % bucketCount;
        BhdEntry* entry = (BhdEntry*)(base + buckets[bucket * 2 + 1]);
        for (uint32_t i = 0; i < buckets[bucket * 2]; ++i, ++entry) {
            if (entry->hash != o.hash) continue;
            Log("loader: %ls -> device %p, was offset %llx size %d%s", o.archivePath.c_str(), device,
                (unsigned long long)entry->offset, entry->size, entry->aesKeyOffset ? " (encrypted)" : "");
            entry->size = (int32_t)o.data.size();
            entry->offset = (int64_t)o.virtualOffset;
            entry->saltedHashOffset = 0;
            entry->aesKeyOffset = 0;
            o.applied = true;
            break;
        }
    }
}

static void* Hooked_EblOpen(void* device, void* path, void* r8, void* r9, void* allocator, unsigned char flag) {
    bool known = false;
    AcquireSRWLockShared(&g_lock);
    for (int i = 0; i < g_patchedDeviceCount; ++i) known |= g_patchedDevices[i] == device;
    ReleaseSRWLockShared(&g_lock);
    if (!known) {
        AcquireSRWLockExclusive(&g_lock);
        bool again = false;
        for (int i = 0; i < g_patchedDeviceCount; ++i) again |= g_patchedDevices[i] == device;
        if (!again && g_patchedDeviceCount < 32) {
            g_patchedDevices[g_patchedDeviceCount++] = device;
            PatchDevice((unsigned char*)device);
        }
        ReleaseSRWLockExclusive(&g_lock);
    }
    return Original_EblOpen(device, path, r8, r9, allocator, flag);
}

// Finds a class vtable from its MSVC RTTI name, e.g. ".?AVDLEncryptedBinderLightFileDevice@DLEBL@@".
static uintptr_t* FindVtable(HMODULE module, const char* rttiName) {
    unsigned char* base = (unsigned char*)module;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_SECTION_HEADER* sections = IMAGE_FIRST_SECTION(nt);
    size_t nameLength = strlen(rttiName) + 1;

    uint32_t typeDescriptorRva = 0;
    for (int s = 0; s < nt->FileHeader.NumberOfSections && !typeDescriptorRva; ++s) {
        unsigned char* p = base + sections[s].VirtualAddress;
        size_t size = sections[s].Misc.VirtualSize;
        for (size_t i = 0x10; i + nameLength <= size; ++i)
            if (p[i] == '.' && memcmp(p + i, rttiName, nameLength) == 0) {
                typeDescriptorRva = (uint32_t)(p + i - 0x10 - base);
                break;
            }
    }
    if (!typeDescriptorRva) return nullptr;

    for (int s = 0; s < nt->FileHeader.NumberOfSections; ++s) {
        unsigned char* p = base + sections[s].VirtualAddress;
        size_t size = sections[s].Misc.VirtualSize;
        for (size_t i = 0; i + 24 <= size; i += 4) {
            uint32_t* col = (uint32_t*)(p + i);  // CompleteObjectLocator: sig, offset, cdOffset, td, chd, self
            if (col[0] != 1 || col[1] != 0 || col[3] != typeDescriptorRva) continue;
            uint32_t colRva = (uint32_t)(p + i - base);
            if (col[5] != colRva) continue;
            uintptr_t colAddress = (uintptr_t)base + colRva;
            for (int t = 0; t < nt->FileHeader.NumberOfSections; ++t) {
                uintptr_t* q = (uintptr_t*)(base + sections[t].VirtualAddress);
                size_t n = sections[t].Misc.VirtualSize / sizeof(uintptr_t);
                for (size_t k = 0; k + 1 < n; ++k)
                    if (q[k] == colAddress) return q + k + 1;
            }
        }
    }
    return nullptr;
}

// ---------------------------------------------------------------- kernel32 imports of the exe
typedef HANDLE(WINAPI* CreateFileW_t)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef BOOL(WINAPI* ReadFile_t)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef BOOL(WINAPI* GetFileInformationByHandle_t)(HANDLE, LPBY_HANDLE_FILE_INFORMATION);
typedef BOOL(WINAPI* CloseHandle_t)(HANDLE);
static CreateFileW_t Original_CreateFileW = nullptr;
static ReadFile_t Original_ReadFile = nullptr;
static GetFileInformationByHandle_t Original_GetFileInformationByHandle = nullptr;
static CloseHandle_t Original_CloseHandle = nullptr;

static HANDLE g_bdtHandles[64];
static int g_bdtHandleCount = 0;
static SRWLOCK g_handleLock = SRWLOCK_INIT;

static bool IsBdt(HANDLE h) {
    bool found = false;
    AcquireSRWLockShared(&g_handleLock);
    for (int i = 0; i < g_bdtHandleCount && !found; ++i) found = g_bdtHandles[i] == h;
    ReleaseSRWLockShared(&g_handleLock);
    return found;
}

// Loose game files (e.g. Game\sfx\sfx9999.ffxbnd.dcx, read through the "title:" root) are not in
// the archives: a file at the same relative path in the mod folder is opened instead.
static std::wstring g_looseGameDir, g_looseModDir;
static std::vector<std::wstring> g_redirectLogged;

static std::wstring LooseReplacement(LPCWSTR name) {
    if (!name || g_looseGameDir.empty()) return L"";
    std::wstring path(name);
    for (wchar_t& c : path) if (c == L'/') c = L'\\';
    if (path.size() <= g_looseGameDir.size() + 1 || _wcsnicmp(path.c_str(), g_looseGameDir.c_str(), g_looseGameDir.size()) != 0 ||
        path[g_looseGameDir.size()] != L'\\')
        return L"";
    std::wstring replacement = g_looseModDir + path.substr(g_looseGameDir.size());
    DWORD attributes = GetFileAttributesW(replacement.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_DIRECTORY)) return L"";
    return replacement;
}

static HANDLE WINAPI Hooked_CreateFileW(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa,
                                        DWORD disposition, DWORD flags, HANDLE templateFile) {
    std::wstring replacement = (access & GENERIC_WRITE) ? L"" : LooseReplacement(name);
    if (!replacement.empty()) {
        AcquireSRWLockExclusive(&g_lock);
        bool first = true;
        for (const std::wstring& p : g_redirectLogged) first &= _wcsicmp(p.c_str(), replacement.c_str()) != 0;
        if (first) g_redirectLogged.push_back(replacement);
        ReleaseSRWLockExclusive(&g_lock);
        if (first) Log("loader: loose file %ls -> %ls", name, replacement.c_str());
        name = replacement.c_str();
    }
    HANDLE h = Original_CreateFileW(name, access, share, sa, disposition, flags, templateFile);
    size_t len = name ? wcslen(name) : 0;
    if (h != INVALID_HANDLE_VALUE && len > 4 && _wcsicmp(name + len - 4, L".bdt") == 0) {
        AcquireSRWLockExclusive(&g_handleLock);
        if (g_bdtHandleCount < 64) g_bdtHandles[g_bdtHandleCount++] = h;
        ReleaseSRWLockExclusive(&g_handleLock);
        Log("loader: tracking %ls (handle %p%s)", name, h, (flags & FILE_FLAG_OVERLAPPED) ? ", overlapped" : "");
    }
    return h;
}

static BOOL WINAPI Hooked_CloseHandle(HANDLE h) {
    AcquireSRWLockExclusive(&g_handleLock);
    for (int i = 0; i < g_bdtHandleCount; ++i)
        if (g_bdtHandles[i] == h) {
            g_bdtHandles[i] = g_bdtHandles[--g_bdtHandleCount];
            break;
        }
    ReleaseSRWLockExclusive(&g_handleLock);
    return Original_CloseHandle(h);
}

static BOOL WINAPI Hooked_GetFileInformationByHandle(HANDLE h, LPBY_HANDLE_FILE_INFORMATION info) {
    BOOL ok = Original_GetFileInformationByHandle(h, info);
    if (ok && IsBdt(h) && !g_overrides.empty()) {
        // cover the virtual range so the operator's seek clamp keeps our offsets
        uint64_t size = kVirtualBase + kVirtualStride * g_overrides.size();
        info->nFileSizeHigh = (DWORD)(size >> 32);
        info->nFileSizeLow = (DWORD)size;
    }
    return ok;
}

static BOOL WINAPI Hooked_ReadFile(HANDLE h, LPVOID buffer, DWORD length, LPDWORD read, LPOVERLAPPED overlapped) {
    if (IsBdt(h)) {
        uint64_t position;
        if (overlapped) {
            position = ((uint64_t)overlapped->OffsetHigh << 32) | overlapped->Offset;
        } else {
            LARGE_INTEGER zero = {}, current = {};
            SetFilePointerEx(h, zero, &current, FILE_CURRENT);
            position = (uint64_t)current.QuadPart;
        }
        if (position >= kVirtualBase) {
            size_t index = (size_t)((position - kVirtualBase) / kVirtualStride);
            uint64_t offset = (position - kVirtualBase) % kVirtualStride;
            memset(buffer, 0, length);
            if (index < g_overrides.size() && offset < g_overrides[index].data.size()) {
                if (!InterlockedExchange(&g_overrides[index].served, 1))
                    Log("loader: serving %ls from the mod folder (first read: %u bytes at +%llx%s)",
                        g_overrides[index].archivePath.c_str(), (unsigned)length, (unsigned long long)offset,
                        overlapped ? ", overlapped" : "");
                size_t n = g_overrides[index].data.size() - (size_t)offset;
                if (n > length) n = length;
                memcpy(buffer, g_overrides[index].data.data() + offset, n);
            }
            // report the full length, as for any entry in the middle of a .bdt
            if (read) *read = length;
            if (overlapped) {
                overlapped->Internal = 0;  // STATUS_SUCCESS: GetOverlappedResult returns InternalHigh
                overlapped->InternalHigh = length;
                if (overlapped->hEvent) SetEvent(overlapped->hEvent);
            } else {
                LARGE_INTEGER advance;
                advance.QuadPart = length;
                SetFilePointerEx(h, advance, nullptr, FILE_CURRENT);
            }
            return TRUE;
        }
    }
    return Original_ReadFile(h, buffer, length, read, overlapped);
}

// ---------------------------------------------------------------- install
bool AnimLoader_Install(const wchar_t* modFolder) {
    g_looseModDir = modFolder;
    g_looseGameDir = g_looseModDir.substr(0, g_looseModDir.find_last_of(L'\\'));
    ScanFolder(modFolder, L"");
    if (g_overrides.empty()) {
        Log("loader: no files in %ls, nothing to override", modFolder);
        return false;
    }

    HMODULE exe = GetModuleHandleA(nullptr);
    uintptr_t* vtable = FindVtable(exe, ".?AVDLEncryptedBinderLightFileDevice@DLEBL@@");
    if (!vtable) {
        Log("loader: archive device vtable not found, loader disabled");
        return false;
    }
    // open() starts with: mov [rsp+8],rbx; mov [rsp+10],rsi; push rdi; sub rsp,30; cmp qword [rdx+18],8
    static const unsigned char kOpenPrologue[] = {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x74, 0x24, 0x10,
                                                  0x57, 0x48, 0x83, 0xEC, 0x30, 0x48, 0x83, 0x7A, 0x18, 0x08};
    if (memcmp((void*)vtable[1], kOpenPrologue, sizeof(kOpenPrologue)) != 0) {
        Log("loader: archive device open() at %p is not the expected code (different game version?), loader disabled",
            (void*)vtable[1]);
        return false;
    }

    struct { const char* name; void* hook; void** original; } imports[] = {
        {"CreateFileW", (void*)&Hooked_CreateFileW, (void**)&Original_CreateFileW},
        {"ReadFile", (void*)&Hooked_ReadFile, (void**)&Original_ReadFile},
        {"GetFileInformationByHandle", (void*)&Hooked_GetFileInformationByHandle, (void**)&Original_GetFileInformationByHandle},
        {"CloseHandle", (void*)&Hooked_CloseHandle, (void**)&Original_CloseHandle},
    };
    for (auto& imp : imports)
        if (!FindImport(exe, "KERNEL32.dll", imp.name)) {
            Log("loader: import %s not found, loader disabled", imp.name);
            return false;
        }
    for (auto& imp : imports) PatchSlot(FindImport(exe, "KERNEL32.dll", imp.name), imp.hook, imp.original);
    PatchSlot(&vtable[1], (void*)&Hooked_EblOpen, (void**)&Original_EblOpen);
    Log("loader: installed (archive device vtable %p, %u override(s))", vtable, (unsigned)g_overrides.size());
    return true;
}
