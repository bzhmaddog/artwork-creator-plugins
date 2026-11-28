//! Tests of the Checkerboard generator, a child module of the crate so they reach its private
//! types.

use super::*;

/// What a catalog of locales/ leaves untranslated.
fn untranslated(catalog: &str) -> Vec<String> {
    artwork_plugin_sdk::untranslated((vec![], vec![Box::new(Checkerboard)]), catalog).unwrap()
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
    Checkerboard
        .generate(&mut img, &Values::from_json(json).unwrap(), px_per_mm)
        .unwrap();
    px
}

/// The default values, as the app gives them.
const DEFAULTS: &str =
    r##"{"size": 10, "color1": "#000000ff", "color2": "#ffffffff", "angle": 0}"##;

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

#[test]
fn offset_shifts_the_squares() {
    // 4 px per mm, squares of 10 mm (40 px): half a square right is 20 px.
    let none = run(DEFAULTS, 120, 40, 4.0);
    let right = run(
        r##"{"size": 10, "color1": "#000000ff", "color2": "#ffffffff", "angle": 0, "offset_x": 50, "offset_y": 0}"##,
        120,
        40,
        4.0,
    );
    let red = |px: &[u8], x: usize, y: usize| px[(y * 120 + x) * 4];
    for y in [5, 20, 35] {
        for x in 25..115 {
            if (x - 20) % 40 > 2 && (x - 20) % 40 < 38 {
                assert_eq!(red(&right, x, y), red(&none, x - 20, y), "{x} {y}");
            }
        }
    }
}

#[test]
fn a_project_saved_before_the_offsets_is_unchanged() {
    let zero = r##"{"size": 10, "color1": "#000000ff", "color2": "#ffffffff", "angle": 0, "offset_x": 0, "offset_y": 0}"##;
    assert_eq!(run(DEFAULTS, 64, 64, 4.0), run(zero, 64, 64, 4.0));
}

#[test]
fn by_count_fills_the_width_with_that_many_squares() {
    // 4 squares across 100 px: color changes every 25 px along a row.
    let px = run(
        r##"{"sizing": "count", "size": 10, "count": 4, "color1": "#000000ff", "color2": "#ffffffff", "angle": 0}"##,
        100,
        30,
        1.0,
    );
    let row: Vec<bool> = (0..100).map(|x| px[(10 * 100 + x) * 4] < 128).collect();
    let changes = row.windows(2).filter(|w| w[0] != w[1]).count();
    assert_eq!(changes, 3, "{row:?}");
    for x in [2, 27, 52, 77] {
        assert_eq!(row[x], row[x + 20], "{x}");
        assert_ne!(row[x], row[(x + 25) % 100], "{x}");
    }
}
