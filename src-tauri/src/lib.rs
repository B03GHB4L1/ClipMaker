use std::net::{TcpListener, TcpStream};
use std::io::{Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::path::BaseDirectory;
use tauri::webview::PageLoadEvent;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_updater::UpdaterExt;

struct BackendProcess(Mutex<Option<(Child, u16)>>);

/// The page asks for an update by navigating here (ui/update.js); the engine
/// answers 204 for the same path, so nothing happens outside the desktop app.
const INSTALL_UPDATE_PATH: &str = "/__vizorplay__/install-update";
static UPDATING: AtomicBool = AtomicBool::new(false);

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn AllowSetForegroundWindow(process_id: u32) -> i32;
}

/// Called by the page just before the engine opens a folder or a web page.
/// Windows only lets the app the user is using bring a new window to the front;
/// those windows open on the engine's behalf, so without this they only flash
/// on the taskbar. The permission lasts until the next foreground change.
/// The pages may call it because build.rs lists it and
/// capabilities/engine-pages.json grants it.
#[tauri::command]
fn allow_foreground() {
    #[cfg(windows)]
    unsafe {
        const ASFW_ANY: u32 = u32::MAX;
        AllowSetForegroundWindow(ASFW_ANY);
    }
}

/// Called by the page after the engine has opened `folder` in Explorer. Explorer
/// may still open it behind VizorPlay, so VizorPlay (the app in front, which
/// Windows lets do this) raises the Explorer window showing that folder. It only
/// looks for and raises an existing Explorer window; it opens nothing.
#[tauri::command]
fn raise_folder_window(folder: String) {
    #[cfg(windows)]
    thread::spawn(move || folder_window::raise(&folder));
    #[cfg(not(windows))]
    let _ = folder;
}

/// Full screen for the app window (F11 or the footer button on every page).
/// `full` sets it; without it the window's current state is only read. The window
/// keeps its state while the pages change, so each page asks when it loads.
#[tauri::command]
fn window_fullscreen(window: tauri::Window, full: Option<bool>) -> Result<bool, String> {
    if let Some(full) = full {
        window.set_fullscreen(full).map_err(|error| error.to_string())?;
    }
    window.is_fullscreen().map_err(|error| error.to_string())
}

#[cfg(windows)]
mod folder_window {
    use std::ffi::c_void;
    use std::time::Duration;

    type Hwnd = *mut c_void;
    const SW_RESTORE: i32 = 9;

    #[link(name = "user32")]
    extern "system" {
        fn EnumWindows(callback: extern "system" fn(Hwnd, isize) -> i32, data: isize) -> i32;
        fn GetClassNameW(window: Hwnd, name: *mut u16, capacity: i32) -> i32;
        fn GetWindowTextW(window: Hwnd, text: *mut u16, capacity: i32) -> i32;
        fn IsWindowVisible(window: Hwnd) -> i32;
        fn IsIconic(window: Hwnd) -> i32;
        fn ShowWindow(window: Hwnd, command: i32) -> i32;
        fn SetForegroundWindow(window: Hwnd) -> i32;
    }

    struct Search {
        titles: Vec<String>,
        found: Hwnd,
    }

    fn text(buffer: &[u16], length: i32) -> String {
        String::from_utf16_lossy(&buffer[..length.clamp(0, buffer.len() as i32) as usize])
    }

    /// Explorer titles its window with the folder name (Windows 11 adds
    /// " - File Explorer", localised) or, if the user chose so, the full path.
    pub(crate) fn title_matches(title: &str, wanted: &[String]) -> bool {
        let title = title.to_lowercase();
        wanted.iter().any(|name| title == *name || title.starts_with(&format!("{name} - ")))
    }

    extern "system" fn visit(window: Hwnd, data: isize) -> i32 {
        let search = unsafe { &mut *(data as *mut Search) };
        let mut class = [0u16; 64];
        let length = unsafe { GetClassNameW(window, class.as_mut_ptr(), class.len() as i32) };
        if text(&class, length) != "CabinetWClass" || unsafe { IsWindowVisible(window) } == 0 {
            return 1;
        }
        let mut title = [0u16; 1024];
        let length = unsafe { GetWindowTextW(window, title.as_mut_ptr(), title.len() as i32) };
        if title_matches(&text(&title, length), &search.titles) {
            search.found = window;
            return 0;
        }
        1
    }

    pub(crate) fn raise(folder: &str) {
        let trimmed = folder.trim_end_matches(['\\', '/']);
        let mut titles = vec![trimmed.to_lowercase()];
        if let Some(name) = std::path::Path::new(trimmed).file_name() {
            titles.push(name.to_string_lossy().to_lowercase());
        }
        // Explorer can take a moment to open the window and set its title.
        for _ in 0..40 {
            let mut search = Search { titles: titles.clone(), found: std::ptr::null_mut() };
            unsafe { EnumWindows(visit, &mut search as *mut Search as isize) };
            if !search.found.is_null() {
                unsafe {
                    if IsIconic(search.found) != 0 {
                        ShowWindow(search.found, SW_RESTORE);
                    }
                    SetForegroundWindow(search.found);
                }
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
}

fn available_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|error| error.to_string())?;
    listener.local_addr().map(|address| address.port()).map_err(|error| error.to_string())
}

/// True once our own backend answers /api/health. Matching the process id
/// rules out another program that took the port after it was released.
fn backend_ready(port: u16, pid: u32) -> bool {
    let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(1)) else {
        return false;
    };
    let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if write!(stream, "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").is_err() {
        return false;
    }
    let mut response = String::new();
    let _ = stream.take(16384).read_to_string(&mut response);
    // The engine is either the spawned process or, for a launcher, its child.
    response.starts_with("HTTP/1.")
        && response.contains(" 200 ")
        && response.contains("\"status\": \"ok\"")
        && (response.contains(&format!("\"pid\": {pid},")) || response.contains(&format!("\"parent_pid\": {pid},")))
}

/// Ask the engine to finish its work and exit, killing it after 20 seconds.
fn stop_backend(app_handle: &AppHandle) {
    let state = app_handle.state::<BackendProcess>();
    let taken = match state.0.lock() {
        Ok(mut guard) => guard.take(),
        Err(_) => None,
    };
    let Some((mut child, port)) = taken else { return };
    if let Ok(mut stream) = TcpStream::connect_timeout(
        &format!("127.0.0.1:{port}").parse().expect("local address"),
        Duration::from_secs(1),
    ) {
        let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
        let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
        let _ = write!(stream, "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}");
        let _ = stream.take(4096).read_to_end(&mut Vec::new());
    }
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        if matches!(child.try_wait(), Ok(Some(_))) { break; }
        thread::sleep(Duration::from_millis(50));
    }
    if matches!(child.try_wait(), Ok(None)) { let _ = child.kill(); }
    let _ = child.wait();
}

/// Tell the page how the update is going (window.vizorplayUpdateStatus).
fn report_update(window: &WebviewWindow, state: &str, detail: &str) {
    let script = format!(
        "window.vizorplayUpdateStatus && window.vizorplayUpdateStatus({}, {});",
        serde_json::Value::from(state),
        serde_json::Value::from(detail),
    );
    let _ = window.eval(&script);
}

/// Only the engine's own page, on its own port, can start an update.
fn is_install_request(url: &Url, port: u16) -> bool {
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port() == Some(port)
        && url.path() == INSTALL_UPDATE_PATH
}

/// Download the update named by the release feed, check its signature against
/// the public key built into this app, stop the engine, and run the installer.
/// On Windows the installer closes VizorPlay, updates it and reopens it.
async fn install_update(app: AppHandle) -> Result<(), String> {
    let mut builder = app.updater_builder();
    // Acceptance tests point at a local https feed. The public key cannot be
    // replaced, so only updates signed with VizorPlay's key ever install.
    if let Some(feed) = std::env::var("VIZORPLAY_UPDATE_URL").ok().filter(|value| !value.is_empty()) {
        let url = Url::parse(&feed).map_err(|error| error.to_string())?;
        builder = builder.endpoints(vec![url]).map_err(|error| error.to_string())?;
    }
    let update = builder
        .build()
        .map_err(|error| error.to_string())?
        .check()
        .await
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "this is already the newest version".to_string())?;
    // download() verifies the signature before returning the installer.
    let installer = update.download(|_, _| {}, || {}).await.map_err(|error| error.to_string())?;
    if let Some(window) = app.get_webview_window("main") {
        report_update(&window, "installing", "");
    }
    // The installer replaces the engine's files, so the engine must exit first.
    stop_backend(&app);
    update
        .install(installer)
        .map_err(|error| format!("{error}. Close VizorPlay and open it again"))?;
    app.restart();
}

const START_FAILED: &str = "document.body.innerHTML = '<main style=\"font:16px system-ui;padding:32px;max-width:640px\"><h1>VizorPlay could not start</h1><p>The local engine stopped or did not answer. Close this window and open VizorPlay again. If it keeps happening, reinstall VizorPlay; security software may have blocked or quarantined part of it.</p></main>';";

/// The window opens hidden: until the engine answers it would only show the
/// webview's empty white page (a white flash, even in the dark theme). It is
/// shown once the app's own page has loaded, which paints the user's theme
/// itself. If the engine is slow, the window is shown sooner on this blank
/// page in the computer's light or dark colour, so the app never looks unopened.
const STARTING: &str = "document.documentElement.style.colorScheme = 'light dark'; document.documentElement.style.background = matchMedia('(prefers-color-scheme: dark)').matches ? '#242424' : '#f7f7f7';";
const SHOW_WITHOUT_ENGINE_AFTER: Duration = Duration::from_millis(2500);

fn reveal(window: &WebviewWindow) {
    if window.is_visible().unwrap_or(false) {
        return;
    }
    let _ = window.show();
    // Windows apps open filling the screen; a hidden window may forget it.
    if cfg!(windows) {
        let _ = window.maximize();
    }
    let _ = window.set_focus();
}

const PREPARING: &str = "document.body.innerHTML ='<main style=\"font:16px system-ui;padding:32px;max-width:640px\"><h1>Preparing VizorPlay</h1><p>The first launch after installing or upgrading sets up VizorPlay&#39;s engine. This can take a few minutes and needs internet access. VizorPlay opens here when it is ready.</p></main>';";

/// Set when Homebrew builds the macOS app on the Mac: the formula's engine
/// launcher, used instead of a frozen engine bundled in the app.
const ENGINE_LAUNCHER: Option<&str> = option_env!("VIZORPLAY_ENGINE_LAUNCHER");

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![allow_foreground, raise_folder_window, window_fullscreen])
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let port = available_port().map_err(std::io::Error::other)?;
            let data_override = std::env::var_os("VIZORPLAY_DATA_DIR").map(std::path::PathBuf::from);
            let (mut command, startup_limit) = match ENGINE_LAUNCHER {
                // Homebrew's launcher prepares the Python engine (minutes on a
                // first launch) and keeps projects where `vizorplay` keeps them.
                Some(launcher) => {
                    let mut command = Command::new(launcher);
                    command.args(["--no-browser", "--port", &port.to_string()]);
                    if let Some(data_dir) = &data_override {
                        command.arg("--data-dir").arg(data_dir);
                    }
                    (command, Duration::from_secs(20 * 60))
                }
                None => {
                    let data_dir = match data_override {
                        Some(data_dir) => data_dir,
                        None => app.path().app_local_data_dir().map_err(|error| {
                            std::io::Error::other(format!("could not find the app data folder: {error}"))
                        })?,
                    };
                    std::fs::create_dir_all(&data_dir)?;
                    let executable = if cfg!(windows) {
                        "backend/vizorplay-engine.exe"
                    } else {
                        "backend/vizorplay-engine"
                    };
                    let server = match app.path().resolve(executable, BaseDirectory::Resource) {
                        Ok(server) => server,
                        Err(error) => {
                            // Tauri reports every failure here as "unknown path". Look beside the
                            // running executable ourselves (Contents/MacOS/../Resources on a Mac)
                            // and keep the underlying error if that fails too.
                            let beside = std::env::current_exe().and_then(|exe| {
                                exe.parent()
                                    .ok_or_else(|| std::io::Error::other("the executable has no folder"))?
                                    .join("../Resources")
                                    .join(executable)
                                    .canonicalize()
                                    .map_err(|e| std::io::Error::new(e.kind(), format!("{e} (looked in {:?})", exe)))
                            });
                            beside.map_err(|fallback| {
                                std::io::Error::other(format!(
                                    "could not locate the bundled engine '{executable}': {error}; looking beside the app: {fallback}"
                                ))
                            })?
                        }
                    };
                    let mut command = Command::new(server);
                    command.args(["--port", &port.to_string()]).current_dir(data_dir);
                    (command, Duration::from_secs(90))
                }
            };
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            let child = command
                .env("VIZORPLAY_OWNER_PID", std::process::id().to_string())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()?;
            let pid = child.id();
            *app.state::<BackendProcess>().0.lock().expect("backend lock") = Some((child, port));

            // The window is created here, not from config alone, so update
            // requests from the page can be intercepted.
            let config = app
                .config()
                .app
                .windows
                .iter()
                .find(|window| window.label == "main")
                .cloned()
                .ok_or_else(|| std::io::Error::other("main window configuration is missing"))?;
            let updater_handle = app.handle().clone();
            let window = WebviewWindowBuilder::from_config(app.handle(), &config)?
                // Windows apps open filling the screen; Mac and Linux keep the configured size.
                .maximized(cfg!(windows) || config.maximized)
                .visible(false)
                .on_page_load(move |window, payload| {
                    if matches!(payload.event(), PageLoadEvent::Finished) && payload.url().port() == Some(port) {
                        reveal(&window);
                    }
                })
                .on_navigation(move |url| {
                    if !is_install_request(url, port) {
                        return true;
                    }
                    // Linux packages and Homebrew update outside the app.
                    if cfg!(windows) && !UPDATING.swap(true, Ordering::SeqCst) {
                        let app = updater_handle.clone();
                        tauri::async_runtime::spawn(async move {
                            if let Some(window) = app.get_webview_window("main") {
                                report_update(&window, "downloading", "");
                            }
                            if let Err(error) = install_update(app.clone()).await {
                                UPDATING.store(false, Ordering::SeqCst);
                                if let Some(window) = app.get_webview_window("main") {
                                    report_update(&window, "error", &error);
                                }
                            }
                        });
                    }
                    false
                })
                .build()?;
            let handle = app.handle().clone();
            thread::spawn(move || {
                let started = Instant::now();
                let deadline = started + startup_limit;
                let mut told_preparing = false;
                let mut shown = false;
                loop {
                    if !shown && started.elapsed() > SHOW_WITHOUT_ENGINE_AFTER {
                        shown = true;
                        let _ = window.eval(STARTING);
                        reveal(&window);
                    }
                    if ENGINE_LAUNCHER.is_some() && !told_preparing && started.elapsed() > Duration::from_secs(3) {
                        told_preparing = true;
                        let _ = window.eval(PREPARING);
                    }
                    if backend_ready(port, pid) {
                        let url = Url::parse(&format!("http://127.0.0.1:{port}"))
                            .expect("valid VizorPlay URL");
                        let _ = window.navigate(url);
                        return;
                    }
                    // Stop waiting as soon as the engine exits, and say so.
                    let exited = handle
                        .state::<BackendProcess>()
                        .0
                        .lock()
                        .ok()
                        .map(|mut guard| match guard.as_mut() {
                            Some((child, _)) => !matches!(child.try_wait(), Ok(None)),
                            None => true,
                        })
                        .unwrap_or(true);
                    if exited || Instant::now() >= deadline {
                        let _ = window.eval(STARTING);
                        let _ = window.eval(START_FAILED);
                        reveal(&window);
                        return;
                    }
                    thread::sleep(Duration::from_millis(250));
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build VizorPlay");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_backend(app_handle);
        }
    });
}
