SRC = src/main.cpp src/steam_fix.cpp src/anim_loader.cpp
GAME_EXE ?= $(HOME)/games/SteamLibrary/steamapps/common/Dark Souls II Scholar of the First Sin/Game/DarkSoulsII.exe
# archived files to ship in the mod folder, as built by ../tools (path inside the archive = path under ../build/<payload>)
PAYLOAD ?= ../build/test-reencode-pray

all: output/dinput8.dll

output/dinput8.dll: $(SRC) src/common.h
	mkdir -p output
	x86_64-w64-mingw32-g++ -shared -static -O2 -Wall $(SRC) -o $@

# offline check of the loader's exe lookups (vtable, prologue, imports, hash) under Wine
test: test/loader_selftest.exe
	WINEDEBUG=-all wine test/loader_selftest.exe "Z:$(subst /,\\,$(GAME_EXE))"

test/loader_selftest.exe: test/loader_selftest.cpp $(SRC) src/common.h
	x86_64-w64-mingw32-g++ -static -O2 -municode -Wl,--image-base,0x10000000 test/loader_selftest.cpp -o $@

# dist/DS2AnimMod: copy its contents next to DarkSoulsII.exe
package: output/dinput8.dll
	rm -rf dist
	mkdir -p dist/DS2AnimMod/DS2AnimMod
	cp output/dinput8.dll DS2AnimMod.ini INSTALL.txt dist/DS2AnimMod/
	cp -r $(PAYLOAD)/. dist/DS2AnimMod/DS2AnimMod/

clean:
	rm -rf output dist test/*.exe
