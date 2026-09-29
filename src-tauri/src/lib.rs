use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::path::BaseDirectory;
use tauri::{Manager, RunEvent, Url};

struct BackendProcess(Mutex<Option<Child>>);

fn available_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|error| error.to_string())?;
    listener.local_addr().map(|address| address.port()).map_err(|error| error.to_string())
}

fn wait_for_backend(port: u16) -> bool {
    let deadline = Instant::now() + Duration::from_secs(90);
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let port = available_port().map_err(std::io::Error::other)?;
            let data_dir = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let executable = if cfg!(windows) {
                "backend/clipmaker-server.exe"
            } else {
                "backend/clipmaker-server"
            };
            let server = app.path().resolve(executable, BaseDirectory::Resource)?;
            let child = Command::new(server)
                .args(["--port", &port.to_string()])
                .current_dir(data_dir)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()?;
            *app.state::<BackendProcess>().0.lock().expect("backend lock") = Some(child);

            let window = app
                .get_webview_window("main")
                .ok_or_else(|| std::io::Error::other("main window is missing"))?;
            thread::spawn(move || {
                if wait_for_backend(port) {
                    let url = Url::parse(&format!("http://127.0.0.1:{port}"))
                        .expect("valid ClipMaker URL");
                    let _ = window.navigate(url);
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build ClipMaker");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            if let Ok(mut guard) = app_handle.state::<BackendProcess>().0.lock() {
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                }
            }
        }
    });
}
