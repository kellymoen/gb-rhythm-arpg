# Combat scene (src/scenes/combat*.c): its UI sheets are only copied to VRAM at scene start, with the
# banked VRAM copy, so they live in a switchable bank instead of scarce bank 0.
UI_BANKED += popups_sprites floor
