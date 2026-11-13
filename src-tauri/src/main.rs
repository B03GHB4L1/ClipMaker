// Release builds are windowed programs on Windows, so no terminal opens beside
// the app (and closing one cannot end it). Debug builds keep the console for logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    clipmaker_lib::run();
}
