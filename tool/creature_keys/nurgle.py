"""The nurgle's own clips - a leap, a paw strike, a wall climb - as key poses read off the user's reference videos (made in the
game project: source_assets/nurgles/nurgle_clip_poses.py; brought here so SF3D's clips of the creature carry them - a retargeting
here used to write werewolf2_open_clips.glb without them). Keyed onto a creature by creature_keyer.py (blender_creature_retarget.py).
The original's notes follow.

Key poses of the nurgle's own clips, read off the user's reference videos (key_nurgle_clips.py keys them; README there).

Units: seconds, metres, degrees. Rig axes: X the creature's left, -Y forward, Z up; the creature stands with its claws at GROUND.
hips: the hips' offset (x, y, z), y > 0 back. rot: bone -> (pitch up, yaw left, roll) relative to its parent; for the tail a positive pitch
lowers the tip. jaw: its own turn, -38 closed (the model was made with the mouth open), 0 open as modelled, more is wider.
legs: g(f, s, u) on the ground f metres ahead of the rest place; b(f, u, s) with the body, from the rest place in the body's frame;
wl(u) on the wall ahead, u metres above the ground. w how much the paw is planted (its sole flat on what it stands on), c the paw's curl
(+ curled, - claws spread), lift / away an arc up / off the wall on the way into that key. A key's "hold" stops every channel it names there.
A channel (hips, jaw, a bone, a leg) must be named in the first and the last key; between, only where it changes.
"""
GROUND = -0.045
REF = dict(hips=0.3611, ground=-0.045)   # the rig the poses were made on: its hips' and claws' heights (another size: scaled)
WALL_Y = -0.52            # the wall's face ahead of the climbing nurgle: its snout touches it standing
WALL_GAP = 0.09           # its wrists off the wall (the claws touch it)
WALL_PAW = -85.0          # the sole turned from the ground onto the wall
TOE_SHARE = 0.8           # the toes curl with the paw
WRIST_FLOOR = {"F": 0.08, "B": 0.03}   # the lowest a wrist / ankle goes above the ground


def g(f=0.0, s=0.0, u=0.0, w=1.0, c=0.0, lift=0.0):
    return dict(sp="g", f=f, s=s, u=u, w=w, c=c, lift=lift)


def b(f=0.0, u=0.0, s=0.0, w=0.0, c=0.0, lift=0.0):
    return dict(sp="b", f=f, s=s, u=u, w=w, c=c, lift=lift)


def wl(u, s=0.0, w=1.0, c=-10.0, away=0.0, lift=0.0):
    return dict(sp="w", u=u, s=s, w=w, c=c, away=away, lift=lift)


def K(t, ease="flow", hips=None, jaw=None, rot=None, **legs):
    return dict(t=t, ease=ease, hips=hips, jaw=jaw, rot=rot or {}, legs=legs)


STAND = dict(FL=g(), FR=g(), BL=g(), BR=g())

# Video 1 (a leap): crouch, the front rises and the forelegs tuck, the hind legs push, a long stretched flight with the forelegs reaching,
# forepaws land first, the hind legs come under the belly, a crouch, the paws step back under the body. Video timing x0.7.
JUMP = dict(name="nurgle_jump", keys=[
    K(0.0, "hold", hips=(0, 0, 0), jaw=-38, **STAND),
    K(0.20, "hold", hips=(0, 0.03, -0.07), jaw=-30, rot=dict(hips=(-3, 0, 0), spine_02=(3, 0, 0), chest=(-4, 0, 0), head=(10, 0, 0),
                                                            tail_01=(12, 0, 0)), FL=g(), FR=g()),
    K(0.32, hips=(0, 0.05, -0.08), jaw=-24, rot=dict(hips=(16, 0, 0), spine_02=(4, 0, 0), chest=(4, 0, 0), head=(-8, 0, 0), tail_01=(0, 0, 0)),
      FL=b(0.04, 0.16, c=100), FR=b(0.02, 0.14, c=100)),
    K(0.44, hips=(0, 0, 0.08), jaw=-8, rot=dict(hips=(12, 0, 0), spine_01=(-3, 0, 0), spine_02=(-3, 0, 0), chest=(0, 0, 0), head=(-4, 0, 0),
                                                tail_01=(-10, 0, 0)),
      FL=b(0.20, 0.14, c=30), FR=b(0.18, 0.12, c=30), BL=g(-0.04), BR=g(-0.02)),
    K(0.62, hips=(0, 0, 0.24), jaw=6, rot=dict(hips=(3, 0, 0), spine_01=(-4, 0, 0), spine_02=(-4, 0, 0), chest=(-2, 0, 0), head=(4, 0, 0),
                                               tail_01=(-18, 0, 0), tail_02=(-6, 0, 0)),
      FL=b(0.28, 0.16, c=-15), FR=b(0.26, 0.18, c=-15), BL=b(-0.30, 0.16, c=80), BR=b(-0.28, 0.17, c=80)),
    K(0.82, hips=(0, 0, 0.17), jaw=0, rot=dict(hips=(-10, 0, 0), spine_01=(0, 0, 0), spine_02=(2, 0, 0), chest=(-2, 0, 0), head=(10, 0, 0),
                                               tail_01=(-12, 0, 0), tail_02=(-4, 0, 0)),
      FL=b(0.20, 0.02, c=-8), FR=b(0.22, 0.0, c=-8), BL=b(0.06, 0.14, c=50), BR=b(0.04, 0.15, c=50)),
    K(0.94, hips=(0, 0, 0.03), jaw=-10, rot=dict(hips=(-14, 0, 0), chest=(-4, 0, 0), head=(14, 0, 0)),
      FL=g(0.12), FR=g(0.10), BL=b(0.10, 0.10, c=20), BR=b(0.08, 0.11, c=20)),
    K(1.06, "hold", hips=(0, 0, -0.08), jaw=-22, rot=dict(hips=(-6, 0, 0), spine_02=(4, 0, 0), chest=(-6, 0, 0), head=(12, 0, 0),
                                                         tail_01=(-6, 0, 0), tail_02=(0, 0, 0)),
      FL=g(0.12), FR=g(0.10), BL=g(0.06), BR=g(0.05)),
    K(1.30, hips=(0, 0.02, -0.04), jaw=-30, rot=dict(hips=(-2, 0, 0), chest=(-2, 0, 0), head=(6, 0, 0), tail_01=(4, 0, 0)),
      FL=g(lift=0.05)),
    K(1.40, FR=g(lift=0.05)),
    K(1.48, BL=g(lift=0.04)),
    K(1.56, BR=g(lift=0.04)),
    K(1.70, "hold", hips=(0, 0, 0), jaw=-38, **STAND),
])

# Video 2 (a paw strike): the weight goes back, the front rears with the forepaws cocked high, mouth wide, a forward rake with the claws
# spread, the right paw slams down ahead and the left after it, a snap of the jaws low, then back. In place: the hind paws stay planted.
PAW_STRIKE = dict(name="nurgle_paw_strike", keys=[
    K(0.0, "hold", hips=(0, 0, 0), jaw=-38, **STAND),
    K(0.20, "hold", hips=(0, 0.05, -0.06), jaw=-30, rot=dict(hips=(3, 0, 0), spine_02=(4, 0, 0), chest=(-6, 0, 0), head=(8, 0, 0),
                                                            tail_01=(8, 0, 0)), FL=g(), FR=g()),
    K(0.46, "hold", hips=(0, 0.07, -0.05), jaw=-6, rot=dict(hips=(28, 0, 0), spine_02=(6, 0, 0), chest=(2, 4, 8), head=(-16, -6, 0),
                                                           tail_01=(-10, 0, 0)),
      FL=b(0.04, 0.20, c=80), FR=b(0.10, 0.32, s=0.06, c=90, lift=0.04)),
    K(0.60, hips=(0, -0.03, -0.01), jaw=8, rot=dict(hips=(10, 0, 0), spine_02=(-2, 0, 0), chest=(-2, -4, -6), head=(4, 4, 0)),
      FL=b(0.22, 0.20, c=40), FR=b(0.36, 0.12, c=-25)),
    K(0.70, "hold", hips=(0, -0.08, -0.06), jaw=-6, rot=dict(hips=(-5, 0, 0), chest=(-8, -2, -4), head=(10, 0, 0)),
      FL=b(0.30, 0.10, c=-20), FR=g(0.20, s=-0.04)),
    K(0.78, "hold", FL=g(0.17, s=-0.02)),
    K(0.90, "hold", hips=(0, -0.09, -0.07), jaw=-42, rot=dict(hips=(-8, 0, 0), head=(2, 0, 0), tail_01=(-8, 0, 0))),
    K(1.12, hips=(0, -0.02, -0.04), jaw=-34, rot=dict(hips=(-3, 0, 0), chest=(-2, 0, 0), head=(4, 0, 0)), FR=g(lift=0.06)),
    K(1.22, FL=g(lift=0.06)),
    K(1.50, "hold", hips=(0, 0, 0), jaw=-38, **STAND),
])

# Video 3 (climbing a wall): a crouch, the body rears up against the wall ahead (its face where the snout is at rest: the hips come
# 0.34 m to it), the forepaws slam onto it and rake down it in turns while the other reaches up, the hind paws step in, leave the ground
# and scrabble up the wall's foot the same way, head up, jaws snapping, the tail swinging for balance. Nothing touches the ground from
# 0.9 s: the horde moves the body up the wall.
_UP = dict(spine_02=(4, 0, 0), chest=(2, 0, 0), tail_02=(-15, 0, 0), tail_03=(-10, 0, 0))
WALL_CLIMB = dict(name="nurgle_wall_climb", keys=[
    K(0.0, "hold", hips=(0, 0, 0), jaw=-38, **STAND),
    K(0.18, "hold", hips=(0, 0.02, -0.05), jaw=-30, rot=dict(hips=(-3, 0, 0), head=(8, 0, 0), tail_01=(5, 0, 0)), FL=g(), FR=g(), BL=g()),
    K(0.30, BR=g()),
    K(0.34, hips=(0, -0.14, -0.03), jaw=-10, rot=dict(hips=(40, 0, 0), spine_02=(5, 0, 0), chest=(5, 0, 0), head=(-25, 0, 0),
                                                     tail_01=(-30, 0, 0)),
      FL=b(0.10, 0.22, c=80), FR=b(0.06, 0.18, c=80)),
    K(0.46, hips=(0, -0.34, -0.08), jaw=4, rot=dict(hips=(74, 0, 0), head=(-40, 0, 0), tail_01=(-65, 8, 0), **_UP),
      FL=wl(0.86), FR=b(0.14, 0.34, c=60), BL=g(0.34, lift=0.07)),
    K(0.56, FR=wl(0.98), BR=g(0.34, lift=0.07)),
    K(0.60, BL=g(0.34)),
    K(0.70, hips=(0, -0.34, -0.06), jaw=-6, rot=dict(chest=(2, 6, 0), head=(-38, -5, 0), tail_01=(-65, -12, 0))),
    K(0.72, BL=wl(0.24, away=0.06)),
    K(0.80, BR=g(0.34)),
    K(0.86, FL=wl(0.66)),
    K(0.92, BR=wl(0.24, away=0.06)),
    K(1.00, hips=(0, -0.34, -0.08), jaw=8, rot=dict(chest=(2, -6, 0), head=(-42, 5, 0), tail_01=(-65, 12, 0))),
    K(1.04, FL=wl(0.96, away=0.08)),
    K(1.08, BL=wl(0.08)),
    K(1.16, FR=wl(0.66)),
    K(1.20, BL=wl(0.24, away=0.06)),
    K(1.30, hips=(0, -0.34, -0.06), jaw=-8, rot=dict(chest=(2, 6, 0), head=(-38, -5, 0), tail_01=(-65, -12, 0))),
    K(1.34, FR=wl(0.96, away=0.08)),
    K(1.38, BR=wl(0.08)),
    K(1.46, FL=wl(0.68)),
    K(1.50, BR=wl(0.24, away=0.06)),
    K(1.56, BL=wl(0.08)),
    K(1.60, hips=(0, -0.34, -0.08), jaw=6, rot=dict(chest=(2, -6, 0), head=(-42, 5, 0), tail_01=(-65, 12, 0))),
    K(1.64, FL=wl(0.96, away=0.08)),
    K(1.68, BL=wl(0.22, away=0.06)),
    K(1.80, "hold", hips=(0, -0.34, -0.07), jaw=-4, rot=dict(hips=(74, 0, 0), head=(-40, 0, 0), tail_01=(-65, 0, 0), **_UP),
      FL=wl(0.88), FR=wl(0.74), BL=wl(0.18), BR=wl(0.12)),
])

CLIPS = [JUMP, PAW_STRIKE, WALL_CLIMB]
