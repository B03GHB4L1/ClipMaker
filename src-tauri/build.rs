fn main() {
    // Listing the app's own commands makes Tauri check them against the
    // capabilities; capabilities/engine-pages.json grants them to the pages
    // the engine serves. Without this the pages' calls are refused by the ACL.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["allow_foreground", "raise_folder_window", "window_fullscreen"]),
    ))
    .expect("failed to run tauri-build");
}
