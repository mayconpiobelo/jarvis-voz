// Esfera flutuante do Jarvis. So exibe: o atalho, o microfone, o Whisper, o Claude e a voz
// continuam no jarvis.py. Esta janela e transparente, fica sempre no topo, nao aparece na barra
// de tarefas, nao recebe foco e deixa os cliques passarem para o que estiver embaixo.
//
// Argumentos (todos opcionais):
//   --corner br|bl|tr|tl|c   canto da tela (padrao: br = inferior direito; c = centro)
//   --size N                 lado da janela em pixels logicos (padrao 420, de 200 a 900)
//   --margin N               distancia da borda em pixels logicos (padrao 24)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;
use tauri::{AppHandle, LogicalSize, Manager, PhysicalPosition, WebviewWindow};

const SERVIDOR: &str = "127.0.0.1:8765";
const URL_OVERLAY: &str = "http://127.0.0.1:8765/overlay";
const URL_PAINEL: &str = "http://127.0.0.1:8765/painel";

/// Pergunta ao Jarvis se o painel deve estar visivel e em qual canto (GET /api/painel, HTTP simples).
fn estado_painel() -> Option<(bool, String)> {
    let addr: SocketAddr = SERVIDOR.parse().ok()?;
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(300)).ok()?;
    s.set_read_timeout(Some(Duration::from_millis(600))).ok()?;
    s.write_all(b"GET /api/painel HTTP/1.0\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\n\r\n").ok()?;
    let mut resp = String::new();
    s.read_to_string(&mut resp).ok()?;
    let c = resp.replace(' ', "");
    let show = c.contains("\"show\":true");
    let canto = c
        .split("\"corner\":\"")
        .nth(1)
        .and_then(|r| r.split('"').next())
        .unwrap_or("tr")
        .to_string();
    Some((show, canto))
}

/// Posiciona o painel no canto pedido, na tela onde esta o mouse (ou na principal).
fn posicionar_painel(app: &AppHandle, w: &WebviewWindow, canto: &str) {
    let monitor = app
        .cursor_position()
        .ok()
        .and_then(|p| app.monitor_from_point(p.x, p.y).ok().flatten())
        .or_else(|| app.primary_monitor().ok().flatten());
    let (Some(m), Ok(tam)) = (monitor, w.outer_size()) else { return };
    let area = m.work_area();
    let mg = (16.0 * m.scale_factor()) as i32;
    let (ax, ay) = (area.position.x, area.position.y);
    let (aw, ah) = (area.size.width as i32, area.size.height as i32);
    let (pw, ph) = (tam.width as i32, tam.height as i32);
    let (x, y) = match canto {
        "tl" => (ax + mg, ay + mg),
        "bl" => (ax + mg, ay + ah - ph - mg),
        "br" => (ax + aw - pw - mg, ay + ah - ph - mg),
        "c" => (ax + (aw - pw) / 2, ay + (ah - ph) / 2),
        _ => (ax + aw - pw - mg, ay + mg), // tr
    };
    let _ = w.set_position(PhysicalPosition::new(x, y));
}

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
            // Painel de widgets: carrega a pagina quando o Jarvis sobe e passa a mostrar/esconder
            // conforme o Jarvis pedir (atalho global, bandeja ou botao).
            if let Some(painel) = app.get_webview_window("painel") {
                let app_h = app.handle().clone();
                std::thread::spawn(move || {
                    let addr: SocketAddr = SERVIDOR.parse().expect("endereco");
                    let mut carregado = false;
                    let mut visivel = false;
                    loop {
                        std::thread::sleep(Duration::from_millis(150));
                        if !carregado {
                            if TcpStream::connect_timeout(&addr, Duration::from_millis(400)).is_ok() {
                                let _ = painel.eval(&format!("window.location.replace('{}')", URL_PAINEL));
                                carregado = true;
                            }
                            continue;
                        }
                        let Some((mostrar, canto)) = estado_painel() else { continue };
                        if mostrar && !visivel {
                            posicionar_painel(&app_h, &painel, &canto);
                            let _ = painel.show();
                            let _ = painel.set_focus();
                            visivel = true;
                        } else if !mostrar && visivel {
                            let _ = painel.hide();
                            visivel = false;
                        }
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o overlay do Jarvis");
}
