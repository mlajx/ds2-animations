// Shared helpers for DS2AnimMod.
#pragma once
#include "windows.h"
#include "stdint.h"

void Log(const char* format, ...);

// IAT slot of DLL!function imported by module, or nullptr.
uintptr_t* FindImport(HMODULE module, const char* dllName, const char* functionName);

// Swap a pointer-sized slot (IAT entry or vtable entry), returning the previous value.
void PatchSlot(uintptr_t* slot, void* hook, void** original);

void SteamFix_Install();
bool AnimLoader_Install(const wchar_t* modFolder);
