//! Tests of the Halftone effect and the Dot grid generator, a child module of the
//! crate so they reach its private types.

use super::*;

/// What a catalog of locales/ leaves untranslated.
fn untranslated(catalog: &str) -> Vec<String> {
    let contents = (
        vec![Box::new(Halftone) as Box<dyn Effect>],
        vec![Box::new(DotGrid) as Box<dyn Generator>],
    );
    artwork_plugin_sdk::untranslated(contents, catalog).unwrap()
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

#[test]
fn leaves_strokes_out() {
    assert!(Halftone.fill_only());
}

/// How much of a 64 x 64 mid-gray square the dots cover, out of 1, with these
/// values.
fn ink(json: &str) -> f32 {
    let (w, h) = (64u32, 64u32);
    // Premultiplied mid gray, opaque.
    let mut px = [128u8, 128, 128, 255].repeat((w * h) as usize);
    let mut img = Image::new(&mut px, w, h, w as usize * 4).unwrap();
    let v = Values::from_json(json).unwrap();
    Halftone.apply(&mut img, &v, 1.0).unwrap();
    let dark = px.chunks(4).filter(|p| p[0] < 64).count();
    dark as f32 / (w * h) as f32
}

#[test]
fn dot_size_leaves_room_between_the_dots() {
    let base =
        r##""size": 8, "angle": 0, "style": "ink", "ink": "#000000ff", "paper": "#ffffffff""##;
    let full = ink(&format!("{{{base}, \"dot_size\": 100}}"));
    let half = ink(&format!("{{{base}, \"dot_size\": 50}}"));
    let none = ink(&format!("{{{base}, \"dot_size\": 0}}"));
    // Area goes with the square of the size.
    assert!((half - full / 4.0).abs() < 0.05, "{full} {half}");
    assert_eq!(none, 0.0);
    // Saved before Dot size: full size.
    assert_eq!(ink(&format!("{{{base}}}")), full);
}

/// The pixels of a 64 x 64 mid-gray square after the effect with these values.
fn dots(json: &str) -> Vec<u8> {
    let (w, h) = (64u32, 64u32);
    let mut px = [128u8, 128, 128, 255].repeat((w * h) as usize);
    let mut img = Image::new(&mut px, w, h, w as usize * 4).unwrap();
    Halftone
        .apply(&mut img, &Values::from_json(json).unwrap(), 1.0)
        .unwrap();
    px
}

#[test]
fn offset_shifts_the_dots() {
    let base =
        r##""size": 8, "angle": 0, "style": "ink", "ink": "#000000ff", "paper": "#ffffffff""##;
    let none = dots(&format!("{{{base}}}"));
    assert_eq!(
        dots(&format!("{{{base}, \"offset_x\": 0, \"offset_y\": 0}}")),
        none
    );
    // Half the spacing to the right: column x now looks like column x - 4.
    let right = dots(&format!("{{{base}, \"offset_x\": 50}}"));
    let down = dots(&format!("{{{base}, \"offset_y\": 50}}"));
    assert_ne!(right, none);
    assert_ne!(down, none);
    let at = |px: &[u8], x: usize, y: usize| px[(y * 64 + x) * 4];
    for y in 8..56 {
        for x in 8..56 {
            assert_eq!(at(&right, x, y), at(&none, x - 4, y), "{x} {y}");
            assert_eq!(at(&down, x, y), at(&none, x, y - 4), "{x} {y}");
        }
    }
}

#[test]
fn dot_grid_covers_the_share_of_a_disc() {
    let (w, h) = (100u32, 100u32);
    let mut px = vec![0u8; (w * h * 4) as usize];
    let mut img = Image::new(&mut px, w, h, w as usize * 4).unwrap();
    let v = Values::from_json(
        r##"{"spacing": 2, "dot_size": 50, "angle": 0, "ink": "#000000ff", "paper": "#ffffff00"}"##,
    )
    .unwrap();
    // 10 px per mm: dots 10 px across, every 20 px.
    DotGrid.generate(&mut img, &v, 10.0).unwrap();
    let inked = px.chunks(4).map(|p| p[3] as f32 / 255.0).sum::<f32>() / (w * h) as f32;
    let disc = std::f32::consts::PI * 25.0 / 400.0;
    assert!((inked - disc).abs() < 0.02, "{inked} {disc}");
}

/// A w x h image of one premultiplied color.
fn filled(px: [u8; 4], w: u32, h: u32) -> Vec<u8> {
    px.repeat((w * h) as usize)
}

const INK: &str =
    r##""size": 8, "angle": 0, "style": "ink", "ink": "#000000ff", "paper": "#ffffffff""##;

/// A light 32 x 16 image, two colors side by side, through a halftone with this paper
/// and "Between the dots" choice.
fn over_two_colors(paper: &str, between: &str) -> (Vec<u8>, [[u8; 4]; 2]) {
    let colors = [[200, 180, 160, 255], [120, 220, 90, 255]];
    let (w, h) = (32u32, 16u32);
    let mut px: Vec<u8> = (0..w * h)
        .flat_map(|i| colors[usize::from(i % w >= w / 2)])
        .collect();
    let mut img = Image::new(&mut px, w, h, w as usize * 4).unwrap();
    let v = Values::from_json(&format!(
        r##"{{"size": 8, "dot_size": 50, "angle": 0, "style": "ink", "ink": "#000000ff", "paper": "{paper}", "between": "{between}"}}"##
    ))
    .unwrap();
    Halftone.apply(&mut img, &v, 1.0).unwrap();
    (px, colors)
}

#[test]
fn the_image_shows_through_transparent_paper() {
    let (px, colors) = over_two_colors("#ff000000", "paper");
    let at = |x: usize, y: usize| &px[(y * 32 + x) * 4..][..4];
    // Between the dots: the image as it was, neither the paper's color nor nothing.
    assert_eq!(at(0, 0), colors[0]);
    assert_eq!(at(24, 8), colors[1]);
    // In a dot: the ink.
    assert_eq!(at(4, 4), [0, 0, 0, 255]);
    assert_eq!(at(28, 12), [0, 0, 0, 255]);
}

#[test]
fn nothing_between_the_dots_leaves_the_image() {
    // Even with an opaque paper: it is not drawn.
    let (px, colors) = over_two_colors("#ffffffff", "nothing");
    let at = |x: usize, y: usize| &px[(y * 32 + x) * 4..][..4];
    // Between the dots: the image as it came.
    assert_eq!(at(0, 0), colors[0]);
    assert_eq!(at(24, 8), colors[1]);
    assert_eq!(at(4, 4), [0, 0, 0, 255]);
    assert_eq!(at(28, 12), [0, 0, 0, 255]);
}

#[test]
fn a_project_saved_before_the_choice_keeps_the_paper() {
    assert_eq!(
        over_two_colors("#ff000000", "").0,
        over_two_colors("#ff000000", "paper").0
    );
}

#[test]
fn white_stays_paper() {
    let mut px = filled([255, 255, 255, 255], 32, 32);
    let mut img = Image::new(&mut px, 32, 32, 32 * 4).unwrap();
    let v = Values::from_json(&format!("{{{INK}}}")).unwrap();
    Halftone.apply(&mut img, &v, 1.0).unwrap();
    assert!(px.iter().all(|&c| c == 255));
}

#[test]
fn transparent_pixels_stay_transparent() {
    let (w, h) = (32u32, 32u32);
    let mut px = filled([0, 0, 0, 0], w, h);
    // An opaque black left half.
    for y in 0..h as usize {
        for x in 0..w as usize / 2 {
            px[(y * w as usize + x) * 4..][..4].copy_from_slice(&[0, 0, 0, 255]);
        }
    }
    let mut img = Image::new(&mut px, w, h, w as usize * 4).unwrap();
    let v = Values::from_json(&format!("{{{INK}}}")).unwrap();
    Halftone.apply(&mut img, &v, 1.0).unwrap();
    for y in 0..h as usize {
        for x in w as usize / 2..w as usize {
            assert_eq!(
                &px[(y * w as usize + x) * 4..][..4],
                &[0, 0, 0, 0],
                "{x} {y}"
            );
        }
    }
    // The black half is dots of ink, nearly all inked.
    let inked = (0..h as usize)
        .flat_map(|y| (0..w as usize / 2).map(move |x| (y, x)))
        .filter(|&(y, x)| px[(y * w as usize + x) * 4] < 64)
        .count();
    assert!(inked as f32 / (w * h / 2) as f32 > 0.75, "{inked}");
}

#[test]
fn darker_gets_more_ink() {
    let cover = |gray: u8| {
        let mut px = filled([gray, gray, gray, 255], 64, 64);
        let mut img = Image::new(&mut px, 64, 64, 64 * 4).unwrap();
        let v = Values::from_json(&format!("{{{INK}}}")).unwrap();
        Halftone.apply(&mut img, &v, 1.0).unwrap();
        px.chunks(4).filter(|p| p[0] < 128).count()
    };
    let (light, mid, dark) = (cover(200), cover(128), cover(40));
    assert!(light < mid && mid < dark, "{light} {mid} {dark}");
}

#[test]
fn image_colors_style_draws_dots_in_the_image_color() {
    let mut px = filled([200, 0, 0, 255], 64, 64);
    let mut img = Image::new(&mut px, 64, 64, 64 * 4).unwrap();
    let v = Values::from_json(
        r##"{"size": 8, "angle": 0, "style": "color", "ink": "#000000ff", "paper": "#ffffffff"}"##,
    )
    .unwrap();
    Halftone.apply(&mut img, &v, 1.0).unwrap();
    // Between red dots and white paper: green and blue move together, red stays high.
    assert!(
        px.chunks(4)
            .all(|p| p[1] == p[2] && p[0] >= 200 && p[3] == 255)
    );
    assert!(px.chunks(4).any(|p| p == [200, 0, 0, 255]));
}

#[test]
fn scale_scales_the_spacing() {
    // Twice the scale on twice the image: the same picture, twice as large.
    let run = |w: u32, scale: f32| {
        let mut px = filled([128, 128, 128, 255], w, w);
        let mut img = Image::new(&mut px, w, w, w as usize * 4).unwrap();
        let v = Values::from_json(&format!("{{{INK}}}")).unwrap();
        Halftone.apply(&mut img, &v, scale).unwrap();
        px.chunks(4).filter(|p| p[0] < 128).count() as f32 / (w * w) as f32
    };
    let (small, large) = (run(64, 1.0), run(128, 2.0));
    assert!((small - large).abs() < 0.03, "{small} {large}");
}

#[test]
fn dot_grid_rejects_a_tiny_spacing() {
    let mut px = vec![0u8; 4 * 4 * 4];
    let mut img = Image::new(&mut px, 4, 4, 16).unwrap();
    let v = Values::from_json(
        r##"{"spacing": 0.5, "dot_size": 50, "angle": 0, "ink": "#000000ff", "paper": "#ffffff00"}"##,
    )
    .unwrap();
    assert!(DotGrid.generate(&mut img, &v, 0.001).is_err());
}

#[test]
fn dot_grid_offset_shifts_the_dots() {
    let grid = |json: &str| {
        let mut px = vec![0u8; 40 * 40 * 4];
        let mut img = Image::new(&mut px, 40, 40, 40 * 4).unwrap();
        DotGrid
            .generate(&mut img, &Values::from_json(json).unwrap(), 10.0)
            .unwrap();
        px
    };
    let base =
        r##""spacing": 2, "dot_size": 50, "angle": 0, "ink": "#000000ff", "paper": "#ffffff00""##;
    let none = grid(&format!("{{{base}}}"));
    // A quarter of the 20 px spacing to the right.
    let right = grid(&format!("{{{base}, \"offset_x\": 25}}"));
    let alpha = |px: &[u8], x: usize, y: usize| px[(y * 40 + x) * 4 + 3];
    for y in 0..40 {
        for x in 5..40 {
            assert_eq!(alpha(&right, x, y), alpha(&none, x - 5, y), "{x} {y}");
        }
    }
}

#[test]
fn ink_and_paper_are_grouped() {
    for params in [Halftone.params(), DotGrid.params()] {
        let grouped: Vec<_> = params
            .iter()
            .filter(|p| p.group.as_deref() == Some("Colors"))
            .map(|p| p.id.as_str())
            .collect();
        assert_eq!(grouped, ["ink", "paper"]);
        assert_eq!(params.iter().filter(|p| p.group.is_some()).count(), 2);
    }
}
