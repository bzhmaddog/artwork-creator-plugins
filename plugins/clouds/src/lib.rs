//! Artwork Creator plugin: a clouds generator, filling a shape with soft cloudy patches
//! mixing two colors.
//!
//! Sizes are in mm and every pixel is worked out from where it lies in mm, so the picture
//! is the same at any resolution, only sharper. Build it with
//! `cargo build --release -p clouds`; released by the Release workflow.

use artwork_plugin_sdk::{Generator, Image, Param, Values, export_plugin};

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

struct Clouds;

impl Generator for Clouds {
    fn id(&self) -> &str {
        "clouds.clouds"
    }

    fn name(&self) -> &str {
        "Clouds"
    }

    fn description(&self) -> &str {
        "Soft cloudy patches mixing the two colors"
    }

    fn params(&self) -> Vec<Param> {
        let mut params = vec![
            mm("size", "Size", 1.0, 500.0, 40.0),
            Param::int("detail", "Detail", 1, 8, 5),
        ];
        params.extend(colors([40, 90, 200, 255], WHITE));
        params.push(Param::seed("seed", "Variation"));
        params
    }

    fn generate(&self, img: &mut Image, v: &Values, px_per_mm: f32) -> Result<(), String> {
        let size = v.f32("size").max(1e-3);
        let detail = v.i32("detail").clamp(1, 8);
        let (a, b, seed) = (v.color("color1"), v.color("color2"), v.i32("seed"));
        fill(img, px_per_mm, |x, y| {
            // Each finer layer half the size and half as strong.
            let (mut sum, mut total, mut k, mut w) = (0.0, 0.0, 1.0 / size, 1.0);
            for o in 0..detail {
                sum += value_noise(x * k, y * k, seed.wrapping_add(o * 7919)) * w;
                total += w;
                k *= 2.0;
                w *= 0.5;
            }
            mix(a, b, sum / total)
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

/// Smooth noise from 0 to 1, one random value per unit cell's corner.
fn value_noise(x: f32, y: f32, seed: i32) -> f32 {
    let (x0, y0) = (x.floor(), y.floor());
    let (fx, fy) = (x - x0, y - y0);
    let (sx, sy) = (fx * fx * (3.0 - 2.0 * fx), fy * fy * (3.0 - 2.0 * fy));
    let (i, j) = (x0 as i64, y0 as i64);
    let top = hash(i, j, seed) + (hash(i + 1, j, seed) - hash(i, j, seed)) * sx;
    let bottom = hash(i, j + 1, seed) + (hash(i + 1, j + 1, seed) - hash(i, j + 1, seed)) * sx;
    top + (bottom - top) * sy
}

export_plugin!(
    name: "Clouds",
    version: env!("CARGO_PKG_VERSION"),
    effects: [],
    generators: [Clouds],
    translations: [
        ("en-US", include_str!("../locales/en-US.json")),
        ("en-GB", include_str!("../locales/en-GB.json")),
        ("fr-FR", include_str!("../locales/fr-FR.json")),
    ],
);

#[cfg(test)]
mod tests;
