# Character sprites: assets/sprites/<name>[_genplaceholder].aseprite
#   -> exports/sprites/<stem>.{png,json,sha1}   (tools/gbtools/export.py; committed, so CI needs no Aseprite)
#   -> $(GEN)/sprite_<name>.{h,c} + spritebank_<name>_<k>.c   (tools/gbtools/sprites.py)
# Included from the Makefile (after the asset_names/asset_path definitions); see docs/sprites.md.

SPRITE_NAMES := $(call asset_names,assets/sprites,.aseprite)
SPRITE_FILES := $(foreach n,$(SPRITE_NAMES),$(call asset_path,assets/sprites,$(n),.aseprite))
SPRITE_BANKS := 1 2 3  # keep in step with BANK_FILES in tools/gbtools/sprites.py

# $(call sprite_rules,<name>,<source .aseprite>)
define sprite_rules
SPRITE_$(1)_STEM := $$(basename $$(notdir $(2)))
SPRITE_$(1)_EXP  := exports/sprites/$$(SPRITE_$(1)_STEM)

$$(SPRITE_$(1)_EXP).json: $(2) tools/gbtools/export.py
	$$(PYTOOLS) gbtools.export --aseprite "$$(ASEPRITE)" exports/sprites $$<

$$(SPRITE_$(1)_EXP).png $$(SPRITE_$(1)_EXP).sha1: $$(SPRITE_$(1)_EXP).json

# The header is the primary target (the converter writes it first); the sources hang off it.
$$(GEN)/sprite_$(1).h: $$(SPRITE_$(1)_EXP).json $$(SPRITE_$(1)_EXP).png tools/gbtools/sprites.py src/core/budgets.h src/core/beat.h src/gb/spritedata.h $$(GEN)/assets.txt
	$$(PYTOOLS) gbtools.sprites $$(SPRITE_$(1)_EXP).png $$(SPRITE_$(1)_EXP).json $$(GEN)

$$(GEN)/sprite_$(1).c $$(SPRITE_BANKS:%=$$(GEN)/spritebank_$(1)_%.c): $$(GEN)/sprite_$(1).h
endef
$(foreach n,$(SPRITE_NAMES),$(eval $(call sprite_rules,$(n),$(call asset_path,assets/sprites,$(n),.aseprite))))

ASSETS  += $(SPRITE_FILES)
GEN_SRC += $(foreach n,$(SPRITE_NAMES),$(GEN)/sprite_$(n).c $(SPRITE_BANKS:%=$(GEN)/spritebank_$(n)_%.c))
GEN_HDR += $(SPRITE_NAMES:%=$(GEN)/sprite_%.h)

# --- placeholders (chained from `make placeholders`) ---
# Lua generators in tools/aseprite/ write assets/sprites/<name>_genplaceholder.aseprite, never over an
# existing one (FORCE_PLACEHOLDERS=1 to regenerate) and never beside your own <name>.aseprite. Then the
# exports are refreshed so they can be committed.
SPRITE_GENERATORS := $(filter-out %/common.lua,$(wildcard tools/aseprite/*.lua))

.PHONY: placeholders-sprites
placeholders: placeholders-sprites
placeholders-sprites:
	@if [ ! -x "$(ASEPRITE)" ]; then echo "skip sprite placeholders: Aseprite not found (ASEPRITE=$(ASEPRITE))"; exit 0; fi; \
	for g in $(SPRITE_GENERATORS); do \
	  "$(ASEPRITE)" -b --script-param root="$(CURDIR)" $(if $(FORCE_PLACEHOLDERS),--script-param force=1) --script $$g || exit 1; \
	done; \
	$(PYTOOLS) gbtools.export --aseprite "$(ASEPRITE)" exports/sprites $$(ls assets/sprites/*_genplaceholder.aseprite 2>/dev/null)
