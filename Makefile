# Beat ARPG build. See CLAUDE.md for targets and flags.

GBDK_HOME ?= $(HOME)/opt/gbdk
LCC       := $(GBDK_HOME)/bin/lcc
UV        ?= uv
ASEPRITE  ?= $(or $(shell command -v aseprite),$(HOME)/Applications/Aseprite.app/Contents/MacOS/aseprite)
EMULICIOUS ?= $(HOME)/opt/emulicious/Emulicious.jar
PYTOOLS   := PYTHONPATH=tools $(UV) run --quiet python -m

NAME  := beatarpg
GEN   := build/gen

ifeq ($(DEBUG),1)
  VARIANT := debug
else
  VARIANT := release
endif
OBJ := build/obj-$(VARIANT)

ifeq ($(DMG),1)
  ROM := build/$(NAME)-dmg$(if $(filter 1,$(DEBUG)),-debug).gb
else
  ROM := build/$(NAME)$(if $(filter 1,$(DEBUG)),-debug).gbc
endif

# Header: MBC5+RAM+BATTERY (0x1B), 1 SRAM bank, auto ROM banks. CGB-compatible (0x80) unless DMG=1.
CFLAGS  := -Isrc -I$(GEN)
LDFLAGS := -Wl-yt0x1B -Wl-j -Wm-yoA -Wm-ya1 -Wm-yn"BEATARPG" -autobank -Wb-ext=.rel
ifneq ($(DMG),1)
  LDFLAGS += -Wm-yc
endif
ifeq ($(DEBUG),1)
  CFLAGS  += -debug -DDEBUG
  LDFLAGS += -debug
endif

SRC := $(wildcard src/core/*.c src/gb/*.c src/audio/*.c src/scenes/*.c)

# Generated sources (build/gen). Rules below avoid grouped targets so they work with GNU Make 3.81.
UI_PNGS   := $(wildcard assets/ui/*.png)
UI_GEN    := $(patsubst assets/ui/%.png,$(GEN)/ui_%,$(UI_PNGS))
SONGS     := $(basename $(notdir $(wildcard assets/music/*.mid)))
MUSIC_SRC := $(GEN)/music_common.c $(SONGS:%=$(GEN)/song_%.c)
GEN_SRC   := $(GEN)/tuning.c $(UI_GEN:%=%.c) $(MUSIC_SRC)
GEN_HDR   := $(GEN)/tuning.h $(UI_GEN:%=%.h) $(GEN)/music.h

OBJS := $(patsubst %.c,$(OBJ)/%.o,$(SRC)) $(patsubst $(GEN)/%.c,$(OBJ)/gen/%.o,$(GEN_SRC))

.PHONY: all test test-host test-tools test-rom run emu listen placeholders clean
all: $(ROM)

$(ROM): $(OBJS)
	$(LCC) $(LDFLAGS) -o $@ $^

# Every object may include generated headers, so generate them first.
$(OBJ)/%.o: %.c $(GEN_HDR)
	@mkdir -p $(dir $@)
	$(LCC) $(CFLAGS) -c -o $@ $<

$(OBJ)/gen/%.o: $(GEN)/%.c $(GEN_HDR)
	@mkdir -p $(dir $@)
	$(LCC) $(CFLAGS) -c -o $@ $<

# A pattern rule with several targets runs its recipe once for all of them.
$(GEN)/%.c $(GEN)/%.h: data/%.toml tools/gbtools/%.py
	$(PYTOOLS) gbtools.$* $< $(GEN)

# assets/ui/foo.png -> ui_foo.{c,h}; files named *_sprites.png are 8x16 sprite sheets.
$(GEN)/ui_%.c $(GEN)/ui_%.h: assets/ui/%.png tools/gbtools/tiles.py
	$(PYTOOLS) gbtools.tiles $< $(GEN) ui_$* $(if $(findstring _sprites,$*),--sprite8x16)

$(GEN)/music.stamp: $(wildcard assets/music/*.mid) assets/music/instruments.toml tools/gbtools/music.py
	$(PYTOOLS) gbtools.music assets/music assets/music/instruments.toml $(GEN)
	@touch $@

$(GEN)/music.h $(MUSIC_SRC): $(GEN)/music.stamp
	@:

# --- host tests: src/core + portable generated data compiled natively ---
HOST_CC     ?= clang
HOST_CFLAGS := -std=c99 -Wall -Wextra -Werror -Isrc -I$(GEN)
HOST_TEST   := build/host/run_tests
HOST_GEN    := $(GEN)/tuning.c

test: test-host test-tools test-rom

test-host: $(HOST_TEST)
	$(HOST_TEST)

$(HOST_TEST): $(wildcard src/core/*.c tests/host/*.c tests/host/*.h) $(HOST_GEN) $(GEN)/tuning.h
	@mkdir -p $(dir $@)
	$(HOST_CC) $(HOST_CFLAGS) -o $@ $(wildcard src/core/*.c tests/host/*.c) $(HOST_GEN)

test-tools:
	$(UV) run --quiet pytest -q tests/tools

# Boots both header variants headless (PyBoy) and compares against tests/rom/golden/.
test-rom:
	$(MAKE) --no-print-directory
	$(MAKE) --no-print-directory DMG=1
	$(MAKE) --no-print-directory DEBUG=1
	$(UV) run --quiet pytest -q tests/rom

run: $(ROM)
	open -a SameBoy $(ROM)

# Hear the current song as the Game Boy plays it (headless emulation -> build/listen.wav).
listen: $(ROM)
	$(PYTOOLS) gbtools.listen $(ROM) build/listen.wav $(or $(SECONDS),20)
	open build/listen.wav

# Write missing placeholder assets (never overwrites; see tools/gbtools/placeholders.py).
placeholders:
	$(PYTOOLS) gbtools.placeholders all

# Emulicious with debugger; pair with DEBUG=1 for C source-level debugging.
emu: $(ROM)
	java -jar $(EMULICIOUS) $(ROM) &

clean:
	rm -rf build
