// Esfera flutuante do Jarvis. So exibe: o atalho, o microfone, o Whisper, o Claude e a voz
// continuam no jarvis.py. Esta janela e transparente, fica sempre no topo, nao aparece na barra
// de tarefas, nao recebe foco e deixa os cliques passarem para o que estiver embaixo.
//
// Argumentos (todos opcionais):
//   --corner br|bl|tr|tl|c   canto da tela (padrao: br = inferior direito; c = centro)
//   --size N                 lado da janela em pixels logicos (padrao 420, de 200 a 900)
//   --margin N               distancia da borda em pixels logicos (padrao 24)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::time::Duration;
use tauri::{LogicalSize, Manager, PhysicalPosition};

const SERVIDOR: &str = "127.0.0.1:8765";
const URL_OVERLAY: &str = "http://127.0.0.1:8765/overlay";

fn arg(nome: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter().position(|x| x == nome).and_then(|i| a.get(i + 1).cloned())
}

fn main() {
    let canto = arg("--corner").unwrap_or_else(|| "br".into());
    let lado: f64 = arg("--size").and_then(|s| s.parse().ok()).unwrap_or(420.0_f64).clamp(200.0, 900.0);
    let margem: f64 = arg("--margin").and_then(|s| s.parse().ok()).unwrap_or(24.0_f64).clamp(0.0, 400.0);

    tauri::Builder::default()
        .setup(move |app| {
            let janela = app.get_webview_window("main").expect("janela principal");

            // Cliques atravessam a esfera: ela nunca atrapalha o que voce esta fazendo.
            let _ = janela.set_ignore_cursor_events(true);
            // Nunca recebe foco (nem por Alt+Tab ou clique acidental) e fica fora da barra de tarefas.
            let _ = janela.set_focusable(false);
            let _ = janela.set_skip_taskbar(true);
            let _ = janela.set_size(LogicalSize::new(lado, lado));

            // Posiciona dentro da area util do monitor (descontando a barra de tarefas).
            if let Ok(Some(m)) = janela.current_monitor() {
                let esc = m.scale_factor();
                let area = m.work_area();
                let w = (lado * esc) as i32;
                let mg = (margem * esc) as i32;
                let (ax, ay) = (area.position.x, area.position.y);
                let (aw, ah) = (area.size.width as i32, area.size.height as i32);
                let (x, y) = match canto.as_str() {
                    "bl" => (ax + mg, ay + ah - w - mg),
                    "tr" => (ax + aw - w - mg, ay + mg),
                    "tl" => (ax + mg, ay + mg),
                    "c" => (ax + (aw - w) / 2, ay + (ah - w) / 2),
                    _ => (ax + aw - w - mg, ay + ah - w - mg), // br
                };
                let _ = janela.set_position(PhysicalPosition::new(x, y));
            }

            // Espera o Jarvis (jarvis.py) subir e so entao carrega a esfera; assim iniciar
            // o overlay antes do servico nao deixa uma tela de erro.
            let j = janela.clone();
            std::thread::spawn(move || {
                let addr: SocketAddr = SERVIDOR.parse().expect("endereco");
                loop {
                    if TcpStream::connect_timeout(&addr, Duration::from_millis(600)).is_ok() {
                        let _ = j.eval(&format!("window.location.replace('{}')", URL_OVERLAY));
                        break;
                    }
                    std::thread::sleep(Duration::from_secs(2));
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o overlay do Jarvis");
}
