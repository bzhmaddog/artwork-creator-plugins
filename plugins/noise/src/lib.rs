//! Artwork Creator plugin: a noise generator, filling a shape with random grains of two
//! colors.
//!
//! Sizes are in mm and every pixel is worked out from where it lies in mm, so the picture
//! is the same at any resolution, only sharper. Build it with
//! `cargo build --release -p noise`; released by the Release workflow.

use artwork_plugin_sdk::{Generator, Image, Param, Values, export_plugin};

const BLACK: [u8; 4] = [0, 0, 0, 255];
const WHITE: [u8; 4] = [255, 255, 255, 255];

fn mm(id: &str, label: &str, min: f32, max: f32, default: f32) -> Param {
    Param::float(id, label, min, max, default)
        .unit("mm")
        .decimals(2)
}

/// The two colors it mixes.
fn colors(a: [u8; 4], b: [u8; 4]) -> [Param; 2] {
    [
        Param::color("color1", "Color 1", a),
        Param::color("color2", "Color 2", b),
    ]
}

struct Noise;

impl Generator for Noise {
    fn id(&self) -> &str {
        "noise.noise"
    }

    fn name(&self) -> &str {
        "Noise"
    }

    fn description(&self) -> &str {
        "Random grains of the two colors"
    }

    fn params(&self) -> Vec<Param> {
        let mut params = vec![mm("size", "Grain", 0.05, 10.0, 0.2)];
        params.extend(colors(BLACK, WHITE));
        params.push(Param::seed("seed", "Variation"));
        params
    }

    fn generate(&self, img: &mut Image, v: &Values, px_per_mm: f32) -> Result<(), String> {
        let size = v.f32("size").max(1e-3);
        let (a, b, seed) = (v.color("color1"), v.color("color2"), v.i32("seed"));
        fill(img, px_per_mm, |x, y| {
            let t = hash((x / size).floor() as i64, (y / size).floor() as i64, seed);
            mix(a, b, t)
        });
        Ok(())
    }
}

/// `a` mixed with `t` of `b`, straight RGBA.
fn mix(a: [u8; 4], b: [u8; 4], t: f32) -> [u8; 4] {
    std::array::from_fn(|i| (a[i] as f32 + (b[i] as f32 - a[i] as f32) * t).round() as u8)
}

/// Sets each pixel to `f(x, y)` of its center, in mm.
fn fill(img: &mut Image, px_per_mm: f32, f: impl Fn(f32, f32) -> [u8; 4] + Sync) {
    let k = 1.0 / px_per_mm.max(1e-6);
    img.par_rows(|y, row| {
        let y = (y as f32 + 0.5) * k;
        for (i, px) in row.as_chunks_mut::<4>().0.iter_mut().enumerate() {
            *px = f((i as f32 + 0.5) * k, y);
        }
    });
}

/// A number from 0 to 1 that only depends on the cell and the seed.
fn hash(x: i64, y: i64, seed: i32) -> f32 {
    let mut h = (x as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15)
        ^ (y as u64).wrapping_mul(0xC2B2_AE3D_27D4_EB4F)
        ^ (seed as u64).wrapping_mul(0x1656_67B1_9E37_79F9);
    h ^= h >> 31;
    h = h.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    h ^= h >> 29;
    (h >> 40) as f32 / (1u64 << 24) as f32
}

export_plugin!(
    name: "Noise",
    version: env!("CARGO_PKG_VERSION"),
    effects: [],
    generators: [Noise],
    translations: [
        ("en-US", include_str!("../locales/en-US.json")),
        ("en-GB", include_str!("../locales/en-GB.json")),
        ("fr-FR", include_str!("../locales/fr-FR.json")),
    ],
);

#[cfg(test)]
mod tests;
