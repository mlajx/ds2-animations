// Offline check of the loader's lookups against a real DarkSoulsII.exe image (run under Wine).
// Usage: loader_selftest.exe PATH\TO\DarkSoulsII.exe
#include "../src/anim_loader.cpp"
#include "../src/main.cpp"  // Log, FindImport (DllMain is unused here)
void SteamFix_Install() {}
#include "stdio.h"

int wmain(int argc, wchar_t** argv) {
    if (argc < 2) return 2;
    HMODULE exe = LoadLibraryExW(argv[1], nullptr, DONT_RESOLVE_DLL_REFERENCES);
    if (!exe) { printf("FAIL load %lu\n", GetLastError()); return 1; }
    int failures = 0;
    uintptr_t* vtable = FindVtable(exe, ".?AVDLEncryptedBinderLightFileDevice@DLEBL@@");
    printf("vtable rva %llx (expect 12928e8)\n", vtable ? (unsigned long long)((unsigned char*)vtable - (unsigned char*)exe) : 0ull);
    failures += !vtable || (unsigned char*)vtable - (unsigned char*)exe != 0x12928e8;
    if (vtable) {
        unsigned long long openRva = vtable[1] - (uintptr_t)exe;
        static const unsigned char kOpenPrologue[] = {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x74, 0x24, 0x10,
                                                      0x57, 0x48, 0x83, 0xEC, 0x30, 0x48, 0x83, 0x7A, 0x18, 0x08};
        bool prologue = memcmp((void*)vtable[1], kOpenPrologue, sizeof(kOpenPrologue)) == 0;
        printf("open rva %llx (expect fef510), prologue %s\n", openRva, prologue ? "ok" : "MISMATCH");
        failures += openRva != 0xfef510 || !prologue;
    }
    for (const char* name : {"CreateFileW", "ReadFile", "GetFileInformationByHandle", "CloseHandle"}) {
        uintptr_t* slot = FindImport(exe, "KERNEL32.dll", name);
        printf("import %-28s %s\n", name, slot ? "ok" : "MISSING");
        failures += !slot;
    }
    uint32_t h = ArchiveHash(L"/morpheme4/chr/c0001.anibnd.dcx");
    printf("hash %08x\n", h);
    printf(failures ? "SELFTEST FAILED (%d)\n" : "SELFTEST OK\n", failures);
    return failures;
}
