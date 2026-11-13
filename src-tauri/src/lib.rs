use std::net::{TcpListener, TcpStream};
use std::io::{Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::path::BaseDirectory;
use tauri::{Manager, RunEvent, Url};

struct BackendProcess(Mutex<Option<(Child, u16)>>);

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

const START_FAILED: &str = "document.body.innerHTML = '<main style=\"font:16px system-ui;padding:32px;max-width:640px\"><h1>VizorPlay could not start</h1><p>The local engine stopped or did not answer. Close this window and open VizorPlay again. If it keeps happening, reinstall VizorPlay; security software may have blocked or quarantined part of it.</p></main>';";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let port = available_port().map_err(std::io::Error::other)?;
            let data_dir = std::env::var_os("VIZORPLAY_DATA_DIR")
                .map(std::path::PathBuf::from)
                .unwrap_or(app.path().app_local_data_dir()?);
            std::fs::create_dir_all(&data_dir)?;
            let executable = if cfg!(windows) {
                "backend/vizorplay-engine.exe"
            } else {
                "backend/vizorplay-engine"
            };
            let server = app.path().resolve(executable, BaseDirectory::Resource)?;
            let mut command = Command::new(server);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            let child = command.args(["--port", &port.to_string()])
                .env("VIZORPLAY_OWNER_PID", std::process::id().to_string())
                .current_dir(data_dir)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()?;
            let pid = child.id();
            *app.state::<BackendProcess>().0.lock().expect("backend lock") = Some((child, port));

            let window = app
                .get_webview_window("main")
                .ok_or_else(|| std::io::Error::other("main window is missing"))?;
            let handle = app.handle().clone();
            thread::spawn(move || {
                let deadline = Instant::now() + Duration::from_secs(90);
                loop {
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
                        let _ = window.eval(START_FAILED);
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
            if let Ok(mut guard) = app_handle.state::<BackendProcess>().0.lock() {
                if let Some((mut child, port)) = guard.take() {
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
            }
        }
    });
}
