// Esfera flutuante e painel rapido do Jarvis. So exibem: o atalho, o microfone, o Whisper, o Claude e a
// voz continuam no jarvis.py. A esfera e transparente, fica sempre no topo, nao aparece na barra de
// tarefas, nao recebe foco e deixa os cliques passarem. O painel e uma janela comum sem moldura que
// voce pode mover e redimensionar; o app lembra onde voce a deixou (o jarvis.py guarda a posicao).
//
// Argumentos (todos opcionais):
//   --corner br|bl|tr|tl|c   canto da tela (padrao: br = inferior direito; c = centro)
//   --size N                 lado da janela em pixels logicos (padrao 420, de 200 a 900)
//   --margin N               distancia da borda em pixels logicos (padrao 24)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, LogicalSize, Manager, PhysicalPosition, PhysicalSize, WebviewWindow, WindowEvent};

const SERVIDOR: &str = "127.0.0.1:8765";
const URL_OVERLAY: &str = "http://127.0.0.1:8765/overlay";
const URL_PAINEL: &str = "http://127.0.0.1:8765/painel";
const PAINEL_LARGURA: f64 = 800.0; // tamanho padrao (pixels logicos)
const PAINEL_ALTURA: f64 = 620.0;

/// Posicao e tamanho do painel em pixels fisicos.
#[derive(Clone, Copy, PartialEq, Debug)]
struct Geo {
    x: i32,
    y: i32,
    w: u32,
    h: u32,
}

/// O que o Jarvis responde em GET /api/painel.
struct EstadoPainel {
    mostrar: bool,
    canto: String,
    geom: Option<Geo>,
    reset: i64,
}

/// Estado compartilhado entre os eventos da janela (thread principal) e o laco que fala com o Jarvis.
struct Compart {
    visivel: bool,
    geo: Geo,
    sujo: bool,                // mudou desde a ultima gravacao
    ultimo_evento: Instant,    // para esperar o usuario parar de arrastar antes de gravar
    ignorar_ate: Instant,      // eventos causados pelo proprio app (set_size/set_position/show) nao contam
    reler_em: Option<Instant>, // depois de posicionar, le a posicao/tamanho reais (o sistema pode ajustar)
}

fn http(metodo: &str, caminho: &str, corpo: Option<&str>) -> Option<String> {
    let addr: SocketAddr = SERVIDOR.parse().ok()?;
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(300)).ok()?;
    s.set_read_timeout(Some(Duration::from_millis(600))).ok()?;
    s.set_write_timeout(Some(Duration::from_millis(600))).ok()?;
    let req = match corpo {
        Some(c) => format!(
            "{metodo} {caminho} HTTP/1.0\r\nHost: {SERVIDOR}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{c}",
            c.len()
        ),
        None => format!("{metodo} {caminho} HTTP/1.0\r\nHost: {SERVIDOR}\r\nConnection: close\r\n\r\n"),
    };
    s.write_all(req.as_bytes()).ok()?;
    let mut resp = String::new();
    s.read_to_string(&mut resp).ok()?;
    Some(resp.split_once("\r\n\r\n").map(|(_, b)| b.to_string()).unwrap_or_default())
}

/// Pergunta ao Jarvis se o painel deve estar visivel, em qual canto e se ha posicao salva.
fn estado_painel() -> Option<EstadoPainel> {
    let v: serde_json::Value = serde_json::from_str(&http("GET", "/api/painel", None)?).ok()?;
    let geom = v.get("geom").and_then(|g| {
        Some(Geo {
            x: i32::try_from(g.get("x")?.as_i64()?).ok()?,
            y: i32::try_from(g.get("y")?.as_i64()?).ok()?,
            w: u32::try_from(g.get("w")?.as_u64()?).ok()?,
            h: u32::try_from(g.get("h")?.as_u64()?).ok()?,
        })
    });
    Some(EstadoPainel {
        mostrar: v.get("show").and_then(|x| x.as_bool()).unwrap_or(false),
        canto: v.get("corner").and_then(|x| x.as_str()).unwrap_or("tr").to_string(),
        geom,
        reset: v.get("reset").and_then(|x| x.as_i64()).unwrap_or(0),
    })
}

fn gravar_geometria(g: Geo) {
    let corpo = format!("{{\"x\":{},\"y\":{},\"w\":{},\"h\":{}}}", g.x, g.y, g.w, g.h);
    let _ = http("POST", "/api/painel/geometria", Some(&corpo));
}

/// A posicao salva ainda cabe em alguma tela? (monitor desligado/trocado nao pode deixar o painel inalcancavel)
fn geometria_valida(app: &AppHandle, g: Geo) -> bool {
    let Ok(monitores) = app.available_monitors() else { return false };
    let (gx2, gy2) = (g.x as i64 + g.w as i64, g.y as i64 + g.h as i64);
    let (cx, cy) = (g.x as i64 + g.w as i64 / 2, g.y as i64 + 30); // meio da barra de cima: onde se agarra
    monitores.iter().any(|m| {
        let a = m.work_area();
        let (ax, ay) = (a.position.x as i64, a.position.y as i64);
        let (ax2, ay2) = (ax + a.size.width as i64, ay + a.size.height as i64);
        let larg = gx2.min(ax2) - (g.x as i64).max(ax);
        let alt = gy2.min(ay2) - (g.y as i64).max(ay);
        let barra_visivel = cx >= ax && cx < ax2 && cy >= ay && cy < ay2;
        larg >= 160 && alt >= 120 && barra_visivel
    })
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

/// Coloca o painel onde o usuario o deixou; sem posicao salva (ou fora das telas), tamanho e canto padrao.
fn aplicar_geometria(app: &AppHandle, w: &WebviewWindow, estado: &EstadoPainel) {
    match estado.geom {
        Some(g) if geometria_valida(app, g) => {
            let _ = w.set_size(PhysicalSize::new(g.w, g.h));
            let _ = w.set_position(PhysicalPosition::new(g.x, g.y));
        }
        _ => {
            let _ = w.set_size(LogicalSize::new(PAINEL_LARGURA, PAINEL_ALTURA));
            posicionar_painel(app, w, &estado.canto);
        }
    }
}

fn arg(nome: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter().position(|x| x == nome).and_then(|i| a.get(i + 1).cloned())
}

fn main() {
    let canto = arg("--corner").unwrap_or_else(|| "br".into());
    let lado: f64 = arg("--size").and_then(|s| s.parse().ok()).unwrap_or(420.0_f64).clamp(200.0, 900.0);
    let margem: f64 = arg("--margin").and_then(|s| s.parse().ok()).unwrap_or(24.0_f64).clamp(0.0, 400.0);

    let agora = Instant::now();
    let comp = Arc::new(Mutex::new(Compart {
        visivel: false,
        geo: Geo { x: 0, y: 0, w: 0, h: 0 },
        sujo: false,
        ultimo_evento: agora,
        ignorar_ate: agora,
        reler_em: None,
    }));
    let comp_eventos = Arc::clone(&comp);

    tauri::Builder::default()
        // O usuario move/redimensiona o painel: so anotamos (sem chamar a janela aqui dentro); o laco
        // abaixo grava depois que ele parar de mexer.
        .on_window_event(move |janela, evento| {
            if janela.label() != "painel" {
                return;
            }
            let Ok(mut c) = comp_eventos.lock() else { return };
            if !c.visivel || Instant::now() < c.ignorar_ate {
                return;
            }
            match evento {
                WindowEvent::Moved(p) if p.x > -30000 && p.y > -30000 => {
                    c.geo.x = p.x;
                    c.geo.y = p.y;
                }
                WindowEvent::Resized(t) if t.width > 0 && t.height > 0 => {
                    c.geo.w = t.width;
                    c.geo.h = t.height;
                }
                _ => return,
            }
            c.sujo = true;
            c.ultimo_evento = Instant::now();
        })
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
            // conforme o Jarvis pedir (atalho global, bandeja ou botao), lembrando onde o usuario o deixou.
            if let Some(painel) = app.get_webview_window("painel") {
                let app_h = app.handle().clone();
                let comp = Arc::clone(&comp);
                std::thread::spawn(move || {
                    let addr: SocketAddr = SERVIDOR.parse().expect("endereco");
                    let mut carregado = false;
                    let mut ultimo_reset: Option<i64> = None;
                    loop {
                        std::thread::sleep(Duration::from_millis(100));
                        if !carregado {
                            if TcpStream::connect_timeout(&addr, Duration::from_millis(400)).is_ok() {
                                let _ = painel.eval(&format!("window.location.replace('{}')", URL_PAINEL));
                                carregado = true;
                            }
                            continue;
                        }

                        // 1) Grava a posicao/tamanho depois que o usuario parou de mexer (0,5 s).
                        let (para_gravar, reler) = {
                            let mut c = comp.lock().unwrap();
                            let g = (c.visivel && c.sujo && c.ultimo_evento.elapsed() > Duration::from_millis(500)
                                && c.geo.w >= 300 && c.geo.h >= 300)
                                .then(|| {
                                    c.sujo = false;
                                    c.geo
                                });
                            let r = matches!(c.reler_em, Some(t) if Instant::now() >= t);
                            if r {
                                c.reler_em = None;
                            }
                            (g, r)
                        };
                        if let Some(g) = para_gravar {
                            gravar_geometria(g);
                        }
                        if reler {
                            // Posicao e tamanho reais depois do show/posicionamento (o sistema pode ter ajustado).
                            if let (Ok(p), Ok(t)) = (painel.outer_position(), painel.outer_size()) {
                                let mut c = comp.lock().unwrap();
                                c.geo = Geo { x: p.x, y: p.y, w: t.width, h: t.height };
                                c.sujo = false;
                            }
                        }

                        // 2) Segue o pedido do Jarvis.
                        let Some(estado) = estado_painel() else { continue };
                        let visivel = comp.lock().unwrap().visivel;
                        let reset_pedido = ultimo_reset.is_some_and(|r| r != estado.reset);
                        ultimo_reset = Some(estado.reset);

                        if estado.mostrar && !visivel {
                            {
                                let mut c = comp.lock().unwrap();
                                c.ignorar_ate = Instant::now() + Duration::from_millis(900);
                                c.reler_em = Some(Instant::now() + Duration::from_millis(1000));
                                c.visivel = true;
                                c.sujo = false;
                            }
                            aplicar_geometria(&app_h, &painel, &estado);
                            let _ = painel.show();
                            let _ = painel.set_focus();
                        } else if !estado.mostrar && visivel {
                            // grava o que ficou pendente antes de esconder
                            let pendente = {
                                let mut c = comp.lock().unwrap();
                                c.visivel = false;
                                let g = (c.sujo && c.geo.w >= 300 && c.geo.h >= 300).then_some(c.geo);
                                c.sujo = false;
                                g
                            };
                            if let Some(g) = pendente {
                                gravar_geometria(g);
                            }
                            let _ = painel.hide();
                        } else if reset_pedido && visivel {
                            // "Restaurar posicao": volta ao tamanho e canto padrao na hora, com o painel aberto
                            {
                                let mut c = comp.lock().unwrap();
                                c.ignorar_ate = Instant::now() + Duration::from_millis(900);
                                c.reler_em = Some(Instant::now() + Duration::from_millis(1000));
                                c.sujo = false;
                            }
                            aplicar_geometria(&app_h, &painel, &estado);
                        }
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o overlay do Jarvis");
}
