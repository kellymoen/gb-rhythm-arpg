# Combo strings and attacks (ADR 0004): data/combos.toml -> build/gen/combos.{c,h,lab.json}.
# A stamp keeps the converter to one run for all three outputs (GNU Make 3.81 has no grouped targets).

COMBOS_OUT := $(GEN)/combos.c $(GEN)/combos.h $(GEN)/combos.lab.json

GEN_SRC  += $(GEN)/combos.c
GEN_HDR  += $(GEN)/combos.h $(GEN)/combos.lab.json
HOST_GEN += $(GEN)/combos.c
LAB_JSON += $(GEN)/combos.lab.json

$(GEN)/combos.stamp: data/combos.toml tools/gbtools/combos.py
	$(PYTOOLS) gbtools.combos $< $(GEN)
	@touch $@

$(COMBOS_OUT): $(GEN)/combos.stamp
	@:
