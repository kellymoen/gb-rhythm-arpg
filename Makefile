# Beat ARPG build. See CLAUDE.md for targets and flags.

GBDK_HOME ?= $(HOME)/opt/gbdk
LCC       := $(GBDK_HOME)/bin/lcc
UV        ?= uv
ASEPRITE  ?= $(or $(shell command -v aseprite),$(HOME)/Applications/Aseprite.app/Contents/MacOS/aseprite)
EMULICIOUS ?= $(HOME)/opt/emulicious/Emulicious.jar
PYTOOLS   := PYTHONPATH=tools $(UV) run --quiet python -m

NAME  := beatarpg

# PLACEHOLDERS=only builds from Claude's placeholders wherever one exists, into build/ph/. The ROM
# tests' goldens use it, so replacing an asset with your own never breaks them (ADR 0007).
ifeq ($(PLACEHOLDERS),only)
  BUILD := build/ph
else
  BUILD := build
endif
GEN   := $(BUILD)/gen

ifeq ($(DEBUG),1)
  VARIANT := debug
else
  VARIANT := release
endif
OBJ := $(BUILD)/obj-$(VARIANT)

ifeq ($(DMG),1)
  ROM := $(BUILD)/$(NAME)-dmg$(if $(filter 1,$(DEBUG)),-debug).gb
else
  ROM := $(BUILD)/$(NAME)$(if $(filter 1,$(DEBUG)),-debug).gbc
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

# --- asset resolution (ADR 0007) ---
# Your <name>.<ext> wins over Claude's <name>_genplaceholder.<ext>. asset_names lists the names in a
# directory; asset_path picks the file for one name. ASSETS collects every resolved file for the report.
PH := _genplaceholder
asset_names = $(sort $(patsubst %$(PH),%,$(basename $(notdir $(wildcard $(1)/*$(2))))))
ifeq ($(PLACEHOLDERS),only)
  asset_path = $(firstword $(wildcard $(1)/$(2)$(PH)$(3) $(1)/$(2)$(3)))
else
  asset_path = $(firstword $(wildcard $(1)/$(2)$(3) $(1)/$(2)$(PH)$(3)))
endif

# Generated sources (build/gen). Rules below avoid grouped targets so they work with GNU Make 3.81.
UI_NAMES    := $(call asset_names,assets/ui,.png)
UI_GEN      := $(UI_NAMES:%=$(GEN)/ui_%)
SONG_NAMES  := $(call asset_names,assets/music,.mid)
SONG_FILES  := $(foreach n,$(SONG_NAMES),$(call asset_path,assets/music,$(n),.mid))
INSTRUMENTS := $(call asset_path,assets/music,instruments,.toml)
MUSIC_SRC   := $(GEN)/music_common.c $(SONG_NAMES:%=$(GEN)/song_%.c)
ASSETS      := $(foreach n,$(UI_NAMES),$(call asset_path,assets/ui,$(n),.png)) $(SONG_FILES) $(INSTRUMENTS)
GEN_SRC     := $(GEN)/tuning.c $(UI_GEN:%=%.c) $(MUSIC_SRC)
GEN_HDR     := $(GEN)/tuning.h $(UI_GEN:%=%.h) $(GEN)/music.h
HOST_GEN    := $(GEN)/tuning.c

# Work packages add their generated sources and rules in mk/<area>.mk (append to GEN_SRC, GEN_HDR,
# HOST_GEN and ASSETS) instead of editing this file.
include $(sort $(wildcard mk/*.mk))

OBJS := $(patsubst %.c,$(OBJ)/%.o,$(SRC)) $(patsubst $(GEN)/%.c,$(OBJ)/gen/%.o,$(GEN_SRC))

.PHONY: all release test test-host test-tools test-rom run emu listen placeholders clean FORCE
all: $(ROM)

# Release ROM: refuses to build while any asset is still a placeholder.
release:
	@$(PYTOOLS) gbtools.assets $(GEN)/assets.txt --release $(ASSETS)
	$(MAKE) --no-print-directory all

# Prints the asset report every build; rewrites the list only when the resolution changes, which
# rebuilds whatever depends on it (e.g. you saved font.png next to font_genplaceholder.png).
$(GEN)/assets.txt: FORCE
	@$(PYTOOLS) gbtools.assets $@ $(ASSETS)

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
.SECONDEXPANSION:
$(GEN)/ui_%.c $(GEN)/ui_%.h: $$(call asset_path,assets/ui,$$*,.png) tools/gbtools/tiles.py $(GEN)/assets.txt
	$(PYTOOLS) gbtools.tiles $< $(GEN) ui_$* $(if $(findstring _sprites,$*),--sprite8x16)

$(GEN)/music.stamp: $(SONG_FILES) $(INSTRUMENTS) tools/gbtools/music.py $(GEN)/assets.txt
	$(PYTOOLS) gbtools.music $(INSTRUMENTS) $(GEN) $(SONG_FILES)
	@touch $@

$(GEN)/music.h $(MUSIC_SRC): $(GEN)/music.stamp
	@:

# --- host tests: src/core + portable generated data compiled natively ---
HOST_CC     ?= clang
HOST_CFLAGS := -std=c99 -Wall -Wextra -Werror -Isrc -I$(GEN)
HOST_TEST   := build/host/run_tests

test: test-host test-tools test-rom

test-host: $(HOST_TEST)
	$(HOST_TEST)

$(HOST_TEST): $(wildcard src/core/*.c tests/host/*.c tests/host/*.h) $(HOST_GEN) $(GEN_HDR)
	@mkdir -p $(dir $@)
	$(HOST_CC) $(HOST_CFLAGS) -o $@ $(wildcard src/core/*.c tests/host/*.c) $(HOST_GEN)

test-tools:
	$(UV) run --quiet pytest -q tests/tools

# Headless PyBoy. Goldens run on the placeholders-only ROMs (build/ph/); the ROM built from your
# assets gets smoke tests only (boots, no missed frames).
test-rom:
	$(MAKE) --no-print-directory PLACEHOLDERS=only
	$(MAKE) --no-print-directory PLACEHOLDERS=only DMG=1
	$(MAKE) --no-print-directory PLACEHOLDERS=only DEBUG=1
	$(MAKE) --no-print-directory
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
