//! Tests of the Stripes generator, a child module of the crate so they reach its private
//! types.

use super::*;

/// What a catalog of locales/ leaves untranslated.
fn untranslated(catalog: &str) -> Vec<String> {
    artwork_plugin_sdk::untranslated((vec![], vec![Box::new(Stripes)]), catalog).unwrap()
}

#[test]
fn every_text_is_in_both_englishes_and_french() {
    for catalog in [
        include_str!("../locales/en-US.json"),
        include_str!("../locales/en-GB.json"),
        include_str!("../locales/fr-FR.json"),
    ] {
        let missing = untranslated(catalog);
        assert!(missing.is_empty(), "{missing:?}");
    }
}

/// The generator's picture over `w` x `h` pixels at `px_per_mm`, with these values.
fn run(json: &str, w: u32, h: u32, px_per_mm: f32) -> Vec<u8> {
    let mut px = vec![0u8; (w * h * 4) as usize];
    let mut img = Image::new(&mut px, w, h, w as usize * 4).unwrap();
    Stripes
        .generate(&mut img, &Values::from_json(json).unwrap(), px_per_mm)
        .unwrap();
    px
}

/// The default values, as the app gives them.
const DEFAULTS: &str =
    r##"{"size": 5, "color1": "#000000ff", "color2": "#ffffffff", "angle": 45}"##;

#[test]
fn fills_the_image_with_both_colors() {
    let px = run(DEFAULTS, 200, 200, 4.0);
    assert!(px.chunks(4).all(|p| p[3] == 255));
    let dark = px.chunks(4).filter(|p| p[0] < 100).count();
    let light = px.chunks(4).filter(|p| p[0] > 155).count();
    assert!(dark > 1000 && light > 1000, "{dark} {light}");
}

#[test]
fn same_picture_at_any_resolution() {
    let low = run(DEFAULTS, 100, 100, 1.0);
    let high = run(DEFAULTS, 400, 400, 4.0);
    // Pixels in the middle of the cells, away from the edges.
    let mut differ = 0;
    for (x, y) in [(13, 27), (50, 50), (71, 8), (90, 61)] {
        let a = low[(y * 100 + x) * 4] as i32;
        let b = high[((y * 4 + 2) * 400 + x * 4 + 2) * 4] as i32;
        differ += ((a - b).abs() > 40) as i32;
    }
    assert!(differ <= 1);
}

/// The red of the pixel at (`x`, `y`) of a `w` pixels wide picture.
fn red(px: &[u8], w: usize, x: usize, y: usize) -> u8 {
    px[(y * w + x) * 4]
}

#[test]
fn a_full_offset_swaps_the_colors() {
    // At 0°, bands 5 mm high; the middle of one band.
    let base = r##"{"size": 5, "color1": "#000000ff", "color2": "#ffffffff", "angle": 0"##;
    let plain = run(&format!("{base}}}"), 40, 40, 1.0);
    let moved = run(&format!(r#"{base}, "offset": 100}}"#), 40, 40, 1.0);
    assert_eq!(red(&plain, 40, 20, 7), 255 - red(&moved, 40, 20, 7));
}
