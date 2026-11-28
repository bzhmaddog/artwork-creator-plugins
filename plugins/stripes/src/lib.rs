//! Artwork Creator plugin: a stripes generator, filling a shape with parallel bands of two
//! colors in turn.
//!
//! Sizes are in mm and every pixel is worked out from where it lies in mm, so the picture
//! is the same at any resolution, only sharper. Build it with
//! `cargo build --release -p stripes`; released by the Release workflow.

use artwork_plugin_sdk::{Generator, Image, Param, Role, Values, export_plugin};

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

fn angle() -> Param {
    Param::float("angle", "Angle", -180.0, 180.0, 45.0)
        .unit("°")
        .decimals(0)
        .role(Role::Angle)
}

struct Stripes;

impl Generator for Stripes {
    fn id(&self) -> &str {
        "stripes.stripes"
    }

    fn name(&self) -> &str {
        "Stripes"
    }

    fn description(&self) -> &str {
        "Parallel bands of the two colors in turn"
    }

    fn params(&self) -> Vec<Param> {
        let mut params = vec![mm("size", "Width", 0.2, 200.0, 5.0)];
        params.extend(colors(BLACK, WHITE));
        params.push(angle());
        params
    }

    fn generate(&self, img: &mut Image, v: &Values, px_per_mm: f32) -> Result<(), String> {
        let size = v.f32("size").max(1e-3);
        let (a, b, deg) = (v.color("color1"), v.color("color2"), v.f32("angle"));
        let px = 1.0 / (px_per_mm * size);
        fill(img, px_per_mm, |x, y| {
            let (_, w) = turned(x, y, deg);
            mix(a, b, 0.5 + 0.5 * square_wave(w / size, px))
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

/// From -1 to 1 across a band edge at `u` (in band widths, a band from 0 to 1 then the
/// next): -1 inside an even band, 1 inside an odd one, blended over about a pixel
/// (`px` band widths) at the edges.
fn square_wave(u: f32, px: f32) -> f32 {
    let f = u.rem_euclid(2.0);
    // Signed distance to the nearest edge, positive in the odd band.
    let d = if f < 1.0 {
        -(f.min(1.0 - f))
    } else {
        (f - 1.0).min(2.0 - f)
    };
    (d / px.max(1e-6) * 2.0).clamp(-1.0, 1.0)
}

/// The coordinates turned by `deg` counterclockwise.
fn turned(x: f32, y: f32, deg: f32) -> (f32, f32) {
    let (s, c) = deg.to_radians().sin_cos();
    // y is down: counterclockwise on the page.
    (x * c - y * s, x * s + y * c)
}

export_plugin!(
    name: "Stripes",
    version: env!("CARGO_PKG_VERSION"),
    effects: [],
    generators: [Stripes],
    translations: [
        ("en-US", include_str!("../locales/en-US.json")),
        ("en-GB", include_str!("../locales/en-GB.json")),
        ("fr-FR", include_str!("../locales/fr-FR.json")),
    ],
);

#[cfg(test)]
mod tests;
