# Sound effects: assets/sfx/<name>.toml -> build/gen/sfx.h, sfx_data.c, sfx.lab.json (docs/sfx.md).

SFX_NAMES := $(call asset_names,assets/sfx,.toml)
SFX_FILES := $(foreach n,$(SFX_NAMES),$(call asset_path,assets/sfx,$(n),.toml))
ASSETS    += $(SFX_FILES)
GEN_SRC   += $(GEN)/sfx_data.c
GEN_HDR   += $(GEN)/sfx.h
LAB_JSON  += $(GEN)/sfx.lab.json

$(GEN)/sfx.stamp: $(SFX_FILES) tools/gbtools/sfx.py $(GEN)/assets.txt
	$(PYTOOLS) gbtools.sfx $(GEN) $(SFX_FILES)
	@touch $@

$(GEN)/sfx.h $(GEN)/sfx_data.c $(GEN)/sfx.lab.json: $(GEN)/sfx.stamp
	@:
