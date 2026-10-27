# Beat ARPG build. See CLAUDE.md for targets and flags.

GBDK_HOME ?= $(HOME)/opt/gbdk
LCC       := $(GBDK_HOME)/bin/lcc
UV        ?= uv
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

SRC     := $(wildcard src/core/*.c src/gb/*.c src/audio/*.c src/scenes/*.c)
GEN_SRC := $(GEN)/tuning.c
GEN_HDR := $(GEN)/tuning.h
OBJS    := $(patsubst %.c,$(OBJ)/%.o,$(SRC)) $(patsubst $(GEN)/%.c,$(OBJ)/gen/%.o,$(GEN_SRC))

.PHONY: all test test-host test-tools test-rom run clean
all: $(ROM)

$(ROM): $(OBJS)
	$(LCC) $(LDFLAGS) -o $@ $^

# Every object may include generated headers, so generate them first.
$(OBJ)/%.o: %.c $(GEN_HDR)
	@mkdir -p $(dir $@)
	$(LCC) $(CFLAGS) -c -o $@ $<

$(OBJ)/gen/%.o: $(GEN)/%.c
	@mkdir -p $(dir $@)
	$(LCC) $(CFLAGS) -c -o $@ $<

$(GEN)/tuning.c $(GEN)/tuning.h &: data/tuning.toml tools/gbtools/tuning.py
	$(PYTOOLS) gbtools.tuning $< $(GEN)

# --- host tests: src/core + generated data compiled natively ---
HOST_CC     ?= clang
HOST_CFLAGS := -std=c99 -Wall -Wextra -Werror -Isrc -I$(GEN)
HOST_TEST   := build/host/run_tests

test: test-host test-tools test-rom

test-host: $(HOST_TEST)
	$(HOST_TEST)

$(HOST_TEST): $(wildcard src/core/*.c tests/host/*.c tests/host/*.h) $(GEN_SRC) $(GEN_HDR)
	@mkdir -p $(dir $@)
	$(HOST_CC) $(HOST_CFLAGS) -o $@ $(wildcard src/core/*.c tests/host/*.c) $(GEN_SRC)

test-tools:
	$(UV) run --quiet pytest -q tests/tools

# Boots both header variants headless (PyBoy) and compares against tests/rom/golden/.
test-rom:
	$(MAKE) --no-print-directory
	$(MAKE) --no-print-directory DMG=1
	$(UV) run --quiet pytest -q tests/rom

run: $(ROM)
	open -a SameBoy $(ROM)

clean:
	rm -rf build
