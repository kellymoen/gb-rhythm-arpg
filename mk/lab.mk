# The feel lab (ADR 0008, docs/lab.md). `make lab` builds the DEBUG ROM and its lab descriptors, then
# starts the lab: a PyBoy window (keyboard-playable, with sound) and a web UI on http://localhost:8750.
# Pass flags through LABFLAGS, e.g. `make lab LABFLAGS="--mute --no-browser --port 9000"`.
#
# Other work packages add their descriptors by appending to LAB_JSON in their own mk file, e.g.
#   LAB_JSON += $(GEN)/combos.lab.json
# and giving that file a rule (it is normally a by-product of the converter that writes the table).

LAB_JSON += $(GEN)/tuning.lab.json

.PHONY: lab lab-descriptors

$(GEN)/tuning.lab.json: data/tuning.toml tools/gbtools/tuning.py
	$(PYTOOLS) gbtools.tuning $< $(GEN)

lab-descriptors: $(LAB_JSON)

lab:
	@$(MAKE) --no-print-directory DEBUG=1 all lab-descriptors
	$(PYTOOLS) lab $(LABFLAGS)
