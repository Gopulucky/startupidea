#!/usr/bin/env python
"""Generate a tiny synthetic Gaussian-splat .ply (standard INRIA 3DGS format)
so the viewer's splat renderer can be tested without a full training run.
Produces a colorful hollow cube of gaussians."""
import struct, sys, math

out = sys.argv[1] if len(sys.argv) > 1 else "public/scans/test-splat.ply"
SH_C0 = 0.28209479177387814

pts = []
N = 14
for i in range(N + 1):
    for j in range(N + 1):
        for k in range(N + 1):
            # keep only the shell of the cube (hollow), so it reads as a room-ish box
            on_shell = i in (0, N) or j in (0, N) or k in (0, N)
            if not on_shell:
                continue
            x = (i / N - 0.5) * 3.0
            y = (j / N - 0.5) * 3.0
            z = (k / N - 0.5) * 3.0
            # color by position -> vivid gradient
            r, g, b = i / N, j / N, k / N
            pts.append((x, y, z, r, g, b))

# full standard INRIA 3DGS layout: 62 float properties per splat
props = (["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
         + [f"f_rest_{i}" for i in range(45)]
         + ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"])
header = ("ply\nformat binary_little_endian 1.0\n"
          f"element vertex {len(pts)}\n"
          + "".join(f"property float {p}\n" for p in props)
          + "end_header\n")

with open(out, "wb") as f:
    f.write(header.encode("ascii"))
    for (x, y, z, r, g, b) in pts:
        fdc = [(c - 0.5) / SH_C0 for c in (r, g, b)]
        rest = [0.0] * 45
        opacity = 6.0                     # pre-sigmoid -> ~0.997
        scale = math.log(0.05)            # log-space -> 5cm blobs
        rot = (1.0, 0.0, 0.0, 0.0)        # identity quaternion (w,x,y,z)
        vals = [x, y, z, 0.0, 0.0, 0.0, *fdc, *rest, opacity, scale, scale, scale, *rot]
        f.write(struct.pack(f"<{len(vals)}f", *vals))

print(f"wrote {out}: {len(pts)} gaussians")
