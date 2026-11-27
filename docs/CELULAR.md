# Jarvis no celular

Um app web instalável (PWA) que o próprio Jarvis serve. Você o abre no Safari do iPhone (ou no Chrome do Android), escolhe **Adicionar à Tela de Início** e ele vira um ícone. Tem a esfera, conversa por **voz** (toque no microfone) ou **texto**, e a aba **Tarefas** (ver, anotar, concluir). A resposta volta **na mesma voz do PC** (Fish → Edge → Kokoro, com as mesmas reservas).

> **Escopo:** no celular o Jarvis só **consulta** (web e agenda) e cuida das **tarefas**: ver, anotar e concluir. Não envia e-mail ou mensagem, não liga, não grava nem apaga arquivos, e remover/desfazer tarefa só pelo PC. Isso é de propósito: o Jarvis do PC roda com acesso amplo, e um celular perdido ou um token vazado não pode ter esse poder.

## Limites
- O **PC precisa estar ligado**, com internet e com o Jarvis rodando; o celular o alcança pelo Tailscale.
- Não existe "Ei Jarvis" com a tela apagada: o iOS não deixa uma página ouvir em segundo plano. Abra o app e toque no microfone.
- A resposta leva de 5 a 15 s (Claude) e a voz mais alguns segundos.
- **Custo e privacidade:** a voz de resposta usa o mesmo motor do PC. Com o Fish, cada resposta falada no celular **gasta o seu saldo** e o texto sai da máquina, como no PC.
- **O PC vem primeiro:** o celular tem sessão própria do Claude (não aparece na esfera nem altera o estado do Jarvis local) e a fecha após 3 min parada (`idle_minutes`). Se você estiver falando com o Jarvis no PC, ou a memória do PC estiver acima de 90% (`mem_max_pct`) sem o Claude do celular aberto, o pedido espera, com um aviso na tela. Se a porta estiver ocupada ou a configuração errada, o servidor do celular não liga e o resto do Jarvis segue normal.

## Segurança
Um servidor **separado** do painel local (porta 8765, que continua só em 127.0.0.1), **desligado por padrão** (`celular.enabled`):
1. **Rede:** só aceita ligar em `127.0.0.1` ou no IP do Tailscale (`100.x.y.z`); `0.0.0.0` e a rede local são recusados na partida.
2. **Token:** a API exige `Authorization: Bearer <token>` (≥ 24 caracteres, comparação em tempo constante); 5 erros seguidos travam o IP por 5 minutos. A página e os ícones não têm nada seu e abrem sem token. O token fica só no aparelho (`localStorage`) e nunca vai na URL enviada ao servidor.
3. **Claude somente-consulta:** `--permission-mode dontAsk` e `--tools` limitado (padrão: `WebSearch`, `WebFetch` e a busca de agenda do Outlook). Sem Bash, sem gravar arquivos, sem e-mail/Teams, sem acesso às suas pastas, e a trava de segurança continua como segunda camada. Foi testado: com uma instrução mandando obedecer tudo, o Write e o Bash continuaram indisponíveis.
4. A página roda com uma política de conteúdo restrita (sem scripts nem recursos de fora) e só insere texto como texto.
5. Pedidos limitados: JSON até 4 KB, gravação até 6 MB (cerca de 1 min), 500 caracteres por pergunta.

O token vale como senha: quem o tiver e alcançar a sua rede Tailscale pode consultar o que o celular consulta (agenda, web) e mexer nas suas tarefas. Mantenha-o só no `config.json`, fora do git.

## Passo a passo
1. **Tailscale:** instale no PC e no iPhone ([tailscale.com](https://tailscale.com)) e entre com a mesma conta. No painel de administração da sua conta, ligue **MagicDNS** e **HTTPS Certificates**.
2. **Token:** `python jarvis.py --celular-token` gera, grava em `config.json` (bloco `celular`) e mostra o token.
3. **Ligar:** em `config.json`, no bloco `celular`, deixe `"host": "127.0.0.1"` e ponha `"enabled": true`. Reinicie o Jarvis.
4. **HTTPS (o microfone do navegador só funciona em HTTPS):** no PC, `tailscale serve --bg 8767` (a sintaxe pode variar com a versão; veja `tailscale serve --help`). O endereço será `https://<nome-do-pc>.<sua-rede>.ts.net`; `tailscale serve status` mostra.
5. **Instalar no iPhone** (Tailscale ligado): no Safari, abra `https://<nome-do-pc>.<sua-rede>.ts.net/#t=<token>`. A página guarda o token e o tira da barra de endereço. Depois: **Compartilhar → Adicionar à Tela de Início**. (Sem o `#t=`, a página pede o token na primeira vez.)
6. Abra o ícone, toque no microfone, libere o acesso ao microfone e fale. Termina sozinho ao ficar em silêncio.

Sem HTTPS (por exemplo, `host` = IP do Tailscale e `http://100.x.y.z:8767`) tudo funciona **menos o microfone**; o texto e as tarefas seguem normais.

## Pontos não verificados
- Testado em ponta a ponta no navegador do computador (login, texto, voz de resposta, tarefas, gravação com fim automático, erros) e a gravação real do navegador foi decodificada com sucesso pelo PC. **Não testado no iPhone nem no Android**: o Safari do iOS tem regras próprias (permissão do microfone, liberação do áudio por toque). Teste e me diga o que falhar.
- `tailscale serve` e as opções do painel do Tailscale não foram executados aqui (o Tailscale não está instalado neste PC).
- Tarefas ditas ("anote tarefa ... para amanhã") usam o mesmo interpretador do PC; frases fora do padrão vão ao Claude, que só consulta e responderá que isso é no computador.

## Ajustes (`config.json` > `celular`)
| Chave | O que faz |
|---|---|
| `enabled` | `true` liga o servidor (padrão `false`) |
| `host` / `port` | Endereço (loopback ou Tailscale) e porta (padrão `127.0.0.1:8767`) |
| `token` | Senha de acesso; `python jarvis.py --celular-token` gera. Para trocar, apague e gere de novo |
| `ferramentas` | Lista das únicas ferramentas liberadas ao Claude do celular. Cada item a mais amplia o que um token vazado pode fazer |
| `persona` | Texto do assistente no celular (use `{dono}` para o nome) |
| `timeout_seconds` | Tempo máximo por pergunta (padrão 60) |
| `idle_minutes` | Fecha o Claude do celular após este tempo parado (padrão 3) |
| `mem_max_pct` | Acima deste uso de memória do PC, o celular espera (padrão 90) |

Teste sem rede: `python jarvis.py --celular-texto "que dia é hoje?"`.
