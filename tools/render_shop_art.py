#!/usr/bin/env python3
"""Raymarch the three shop products as photographic product shots.

Signed-distance geometry, soft shadows, ambient occlusion, a GGX-ish specular
lobe and a filmic tonemap. The parts are plain solids -- boxes, cylinders,
capsules -- so distance fields describe them exactly and render far better than
drawing them flat ever did.

    python3 render3d.py <drum-key|xr18-ears|stick-holder> out.png [scale]
"""

import sys
import numpy as np

np.seterr(all="ignore")

# ---------------------------------------------------------------- primitives

def v3(x, y, z):
    return np.array([x, y, z], dtype=np.float32)


def length(p, axis=-1, keepdims=False):
    return np.sqrt(np.sum(p * p, axis=axis, keepdims=keepdims))


def sd_round_box(p, c, b, r):
    q = np.abs(p - c) - b
    return (length(np.maximum(q, 0.0))
            + np.minimum(np.max(q, axis=-1), 0.0) - r)


def sd_cyl_y(p, c, h, r):
    """Capped cylinder along Y."""
    d = p - c
    dxz = np.sqrt(d[..., 0] ** 2 + d[..., 2] ** 2) - r
    dy = np.abs(d[..., 1]) - h
    return (np.minimum(np.maximum(dxz, dy), 0.0)
            + np.sqrt(np.maximum(dxz, 0.0) ** 2 + np.maximum(dy, 0.0) ** 2))


def sd_cyl_axis(p, c, h, r, axis):
    """Capped cylinder along x(0), y(1) or z(2)."""
    d = p - c
    o = [0, 1, 2]
    o.remove(axis)
    dr = np.sqrt(d[..., o[0]] ** 2 + d[..., o[1]] ** 2) - r
    da = np.abs(d[..., axis]) - h
    return (np.minimum(np.maximum(dr, da), 0.0)
            + np.sqrt(np.maximum(dr, 0.0) ** 2 + np.maximum(da, 0.0) ** 2))


def sd_capsule(p, a, b, r):
    pa = p - a
    ba = b - a
    h = np.clip(np.sum(pa * ba, axis=-1) / np.sum(ba * ba), 0.0, 1.0)
    return length(pa - ba * h[..., None]) - r


def op_u(a, b):
    return np.minimum(a, b)


def op_sub(a, b):
    """a minus b."""
    return np.maximum(a, -b)


# -------------------------------------------------------------------- scenes
# Material ids: 0 floor, 1 orange filament, 2 dark plastic, 3 metal, 4 wood,
# 5 screen glow.

FLOOR_Y = -2.6


def scene_drum_key(p):
    d = sd_round_box(p, v3(0, 3.55, 0), v3(2.75, 0.30, 0.42), 0.34)   # handle
    d = op_sub(d, sd_cyl_axis(p, v3(-2.05, 3.55, 0), 1.0, 0.34, 2))   # ring hole
    d = op_u(d, sd_round_box(p, v3(0, 1.35, 0), v3(0.26, 1.85, 0.26), 0.14))
    head = sd_round_box(p, v3(0, -0.88, 0), v3(0.88, 0.92, 0.88), 0.16)
    head = op_sub(head, sd_round_box(p, v3(0, -1.92, 0), v3(0.40, 0.72, 0.40), 0.05))
    d = op_u(d, head)
    return d, np.ones(d.shape, np.int8)


def scene_xr18(p):
    body = sd_round_box(p, v3(0, 0.55, 0), v3(2.45, 1.45, 1.75), 0.14)
    d, m = body, np.full(body.shape, 2, np.int8)

    knobs = np.full(body.shape, 1e9, np.float32)
    for kx in (-1.05, 0.0, 1.05):
        knobs = op_u(knobs, sd_cyl_y(p, v3(kx, 2.02, -0.55), 0.17, 0.26))
    d = op_u(d, knobs)
    m = np.where(knobs < d + 1e-4, 3, m)

    screen = sd_round_box(p, v3(0, 2.01, 0.72), v3(1.35, 0.06, 0.52), 0.04)
    d2 = op_u(d, screen)
    m = np.where(screen <= d, 5, m)
    d = d2

    ears = np.full(body.shape, 1e9, np.float32)
    for s in (-1.0, 1.0):
        flange = sd_round_box(p, v3(s * 3.35, 0.55, 1.35), v3(0.78, 2.70, 0.18), 0.10)
        flange = op_sub(flange, sd_cyl_axis(p, v3(s * 3.35, 2.05, 1.35), 1.0, 0.26, 2))
        flange = op_sub(flange, sd_cyl_axis(p, v3(s * 3.35, -0.95, 1.35), 1.0, 0.26, 2))
        arm = sd_round_box(p, v3(s * 2.95, 0.55, 0.25), v3(0.38, 0.72, 1.30), 0.10)
        ears = op_u(ears, op_u(flange, arm))
    m = np.where(ears < d, 1, m)
    d = op_u(d, ears)
    return d, m


def scene_stick_holder(p):
    tube = sd_cyl_y(p, v3(-2.75, 1.2, 0), 3.9, 0.52)
    d, m = tube, np.full(tube.shape, 3, np.int8)

    cup_o = sd_cyl_y(p, v3(0.55, 0.35, 0), 1.75, 1.42)
    cup = op_sub(cup_o, sd_cyl_y(p, v3(0.55, 0.75, 0), 1.65, 1.18))
    clamp = sd_round_box(p, v3(-1.75, 0.35, 0), v3(0.95, 0.70, 0.70), 0.16)
    clamp = op_sub(clamp, sd_cyl_y(p, v3(-2.75, 0.35, 0), 2.0, 0.54))
    orange = op_u(cup, clamp)
    m = np.where(orange < d, 1, m)
    d = op_u(d, orange)

    sticks = sd_capsule(p, v3(0.1, 1.2, 0.25), v3(-0.8, 5.1, 0.75), 0.17)
    sticks = op_u(sticks, sd_capsule(p, v3(1.0, 1.2, -0.2), v3(2.1, 5.3, -0.6), 0.17))
    m = np.where(sticks < d, 4, m)
    d = op_u(d, sticks)
    return d, m


SCENES = {
    #                scene                look               dist  camera
    "drum-key":     (scene_drum_key,     v3(0.0, 1.0, 0.0), 15.5, v3(5.0, 3.1, 12.6)),
    "xr18-ears":    (scene_xr18,         v3(0.0, 0.6, 0.0), 18.6, v3(4.3, 5.0, 11.2)),
    "stick-holder": (scene_stick_holder, v3(0.0, 2.3, 0.0), 20.0, v3(5.0, 3.3, 12.6)),
}

# ------------------------------------------------------------------- shading

ALBEDO = {
    0: (0.055, 0.050, 0.050),
    1: (0.70, 0.155, 0.022),
    2: (0.085, 0.078, 0.082),
    3: (0.52, 0.53, 0.56),
    4: (0.72, 0.56, 0.33),
    5: (0.06, 0.26, 0.21),
}
ROUGH = {0: 0.42, 1: 0.40, 2: 0.52, 3: 0.24, 4: 0.55, 5: 0.22}


def make_scene(fn):
    def sdf(p):
        d, m = fn(p)
        fl = p[..., 1] - FLOOR_Y
        m = np.where(fl < d, 0, m)
        return np.minimum(d, fl), m
    return sdf


def march(sdf, ro, rd, steps=110, far=48.0):
    t = np.full(rd.shape[:-1], 0.02, np.float32)
    hit = np.zeros(t.shape, bool)
    for _ in range(steps):
        p = ro + rd * t[..., None]
        d, _ = sdf(p)
        d = np.where(hit, 1e9, d)
        t = np.minimum(t + np.where(hit, 0.0, d * 0.92), far)
        hit |= d < 0.0012
    return t, hit


def normal(sdf, p):
    e = 0.0016
    n = np.empty(p.shape, np.float32)
    for i in range(3):
        o = np.zeros(3, np.float32)
        o[i] = e
        n[..., i] = sdf(p + o)[0] - sdf(p - o)[0]
    return n / np.maximum(length(n, keepdims=True), 1e-9)


def soft_shadow(sdf, p, ldir, k=14.0, steps=46):
    t = np.full(p.shape[:-1], 0.05, np.float32)
    res = np.ones(t.shape, np.float32)
    for _ in range(steps):
        d, _ = sdf(p + ldir * t[..., None])
        res = np.minimum(res, k * d / np.maximum(t, 1e-4))
        t += np.clip(d, 0.02, 1.1)
    return np.clip(res, 0.0, 1.0)


def ao(sdf, p, n, samples=6):
    occ = np.zeros(p.shape[:-1], np.float32)
    w = 1.0
    for i in range(1, samples + 1):
        h = 0.035 * i * i
        d, _ = sdf(p + n * h)
        occ += (h - d) * w
        w *= 0.72
    return np.clip(1.0 - 2.6 * occ, 0.0, 1.0)


def ggx(n, v, l, rough):
    h = v + l
    h /= np.maximum(length(h, keepdims=True), 1e-9)
    ndh = np.clip(np.sum(n * h, -1), 0, 1)
    ndv = np.clip(np.sum(n * v, -1), 0, 1)
    ndl = np.clip(np.sum(n * l, -1), 0, 1)
    a = np.maximum(rough * rough, 1e-3)
    d = a * a / np.maximum(np.pi * (ndh * ndh * (a * a - 1) + 1) ** 2, 1e-9)
    k = a / 2.0
    g = (ndl / np.maximum(ndl * (1 - k) + k, 1e-9)) * (ndv / np.maximum(ndv * (1 - k) + k, 1e-9))
    f = 0.045 + 0.955 * (1 - ndv) ** 5
    return d * g * f


def aces(x):
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


def render(name, out, scale=2):
    fn, look, dist, cam = SCENES[name]
    sdf = make_scene(fn)

    W, H = 900 * scale, 630 * scale
    aspect = W / H

    ro = look + cam / np.linalg.norm(cam) * dist
    fw = look - ro
    fw /= np.linalg.norm(fw)
    rt = np.cross(fw, v3(0, 1, 0))
    rt /= np.linalg.norm(rt)
    up = np.cross(rt, fw)

    x = (np.arange(W, dtype=np.float32) + 0.5) / W * 2 - 1
    y = 1 - (np.arange(H, dtype=np.float32) + 0.5) / H * 2
    gx, gy = np.meshgrid(x * aspect, y)
    fov = np.tan(np.radians(30.0) / 2)
    rd = fw + rt * (gx * fov)[..., None] + up * (gy * fov)[..., None]
    rd /= length(rd, keepdims=True)
    ro_b = np.broadcast_to(ro, rd.shape)

    t, hit = march(sdf, ro_b, rd)
    p = ro_b + rd * t[..., None]
    _, mat = sdf(p)
    n = normal(sdf, p)

    # Print layer lines on the filament parts: a shallow ripple in the normal,
    # which is what actually gives a printed part away under a light.
    ripple = np.sin(p[..., 1] * 46.0) * 0.045
    side = np.stack([n[..., 0], np.zeros_like(n[..., 1]), n[..., 2]], -1)
    side /= np.maximum(length(side, keepdims=True), 1e-9)
    lay = (mat == 1) | (mat == 2)
    n = np.where(lay[..., None], n + side * ripple[..., None], n)
    n /= np.maximum(length(n, keepdims=True), 1e-9)

    key = v3(-0.52, 0.72, 0.45); key /= np.linalg.norm(key)
    fill = v3(0.78, 0.26, 0.55); fill /= np.linalg.norm(fill)
    rim = v3(0.18, 0.30, -0.92); rim /= np.linalg.norm(rim)
    view = -rd

    alb = np.zeros(p.shape, np.float32)
    rough = np.zeros(t.shape, np.float32)
    for mid, c in ALBEDO.items():
        sel = mat == mid
        alb[sel] = c
        rough[sel] = ROUGH[mid]

    # A pool of light on the floor so the sweep is lit rather than flat black.
    r2 = np.sqrt((p[..., 0] - 0.4) ** 2 + (p[..., 2] - 0.2) ** 2)
    pool = np.exp(-(r2 / 7.2) ** 2)
    alb = np.where((mat == 0)[..., None], alb * (0.55 + 1.5 * pool[..., None]), alb)

    sh = soft_shadow(sdf, p + n * 0.012, key)
    occ = ao(sdf, p, n)

    ndl_k = np.clip(np.sum(n * key, -1), 0, 1)
    ndl_f = np.clip(np.sum(n * fill, -1), 0, 1)
    ndl_r = np.clip(np.sum(n * rim, -1), 0, 1)

    col = alb * (ndl_k * sh * 1.42)[..., None]
    col += alb * (ndl_f * (0.11 + 0.09 * occ))[..., None]
    col += alb * (ndl_r ** 2.2 * 0.42 * occ)[..., None]
    col += alb * (0.055 * occ)[..., None]
    col += (ggx(n, view, key, rough) * sh * 1.5)[..., None] * np.float32([1.0, 0.96, 0.9])
    col += (ggx(n, view, rim, rough) * 0.5)[..., None] * np.float32([0.75, 0.82, 1.0])
    col[mat == 5] += np.float32([0.05, 0.55, 0.42])

    # Background: a lit sweep that falls off, not a flat fill.
    bgy = np.clip(gy * 0.5 + 0.5, 0, 1)
    bg = (np.float32([0.072, 0.060, 0.058])[None, None, :] * (0.35 + 0.95 * bgy[..., None])
          + np.float32([0.11, 0.055, 0.03])[None, None, :]
          * np.exp(-(((gx - 0.1) ** 2 + (gy - 0.15) ** 2) / 0.46))[..., None])
    col = np.where(hit[..., None], col, bg)

    # Haze with distance, so the far side of the sweep recedes.
    fog = np.clip((t - dist * 0.72) / (dist * 1.5), 0, 1)[..., None]
    col = col * (1 - fog * 0.55) + np.float32([0.055, 0.045, 0.045]) * fog * 0.55

    col = aces(col * 1.0)
    col = np.power(np.clip(col, 0, 1), 1 / 2.2)

    vig = 1.0 - 0.34 * ((gx / aspect) ** 2 + gy ** 2)
    col *= np.clip(vig, 0, 1)[..., None]

    rng = np.random.default_rng(7)
    col += rng.normal(0, 0.0055, col.shape).astype(np.float32)

    img = (np.clip(col, 0, 1) * 255).astype(np.uint8)
    from PIL import Image
    im = Image.fromarray(img, "RGB")
    if scale != 1:
        im = im.resize((900, 630), Image.LANCZOS)
    im.save(out, quality=88, optimize=True, progressive=True)
    print("wrote", out)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2)
