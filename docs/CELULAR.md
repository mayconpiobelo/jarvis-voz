# Jarvis no celular

Um app web instalável (PWA) que o próprio Jarvis serve. Você o abre no Safari do iPhone (ou no Chrome do Android), escolhe **Adicionar à Tela de Início** e ele vira um ícone. Tem quatro abas, no mesmo visual de vidro e degradê do painel do PC: **Falar** (a esfera em tela cheia, igual à do PC: uma nuvem de pontos 3D que gira, pulsa com a sua voz e com a voz do Jarvis e ganha anéis ao pensar; toque nela ou no microfone para falar; embaixo fica a legenda do que você disse e da resposta), **Conversa** (o histórico em balões, com o campo para digitar), **Painel** (cartões com o clima da sua cidade, a CPU e a memória do PC, o consumo do Claude com a hora em que reinicia, um resumo das tarefas e a música que toca no PC) e **Tarefas** (ver, anotar, concluir). A resposta volta **na mesma voz do PC** (Fish → Edge → Kokoro, com as mesmas reservas).

## Dois modos de acesso (`celular.acesso`)
| | `"consulta"` (padrão) | `"completo"` |
|---|---|---|
| O que o Claude pode | Web e agenda do Outlook | **As mesmas ferramentas do PC**: e-mail, calendário, Teams, SharePoint, arquivos, comandos |
| Ações que saem para fora ou mexem em coisas importantes (enviar e-mail, criar convite, escrever fora da sua pasta...) | Não existem | O Jarvis **propõe** e a tela mostra **Confirmar / Cancelar**; só executa depois do seu toque |
| Apagar e comandos destrutivos | Bloqueados | **Bloqueados de vez**, como no PC (`deny_always`) |
| Tarefas | Ver, anotar, concluir | Ver, anotar, concluir (remover e desfazer só no PC) |

O modo **completo** exige a trava de segurança ligada (`confirm_by_voice` ligado e `allow_outward_actions` desligado); sem ela o Jarvis ignora o pedido e fica em `consulta`.

### Como funciona o modo completo
1. Você pede, por voz ou texto: "envie um e-mail para a Ana dizendo que chego às 15h", "o que tenho na agenda amanhã?", "cria um convite para sexta às 10h".
2. Leituras (agenda, e-mails, arquivos, Teams) acontecem direto, e a resposta aparece na tela com as linhas inteiras; a voz fala só o começo e avisa que o resto está na tela.
3. Se o pedido **age para fora**, a trava barra a ferramenta e o Jarvis responde o que vai fazer (destinatário, texto, hora) e termina com "Confirma, senhor?". A tela mostra **Confirmar** e **Cancelar**. Dizer ou digitar "sim" ou "não" também vale.
4. Ao tocar em **Confirmar**, a trava libera **só aquela sessão do celular**, por no máximo 2 minutos (`confirm_ttl_seconds`), e só para aquela ação. A confirmação falada no PC não vale no celular, e a do celular não vale no PC.
5. Um novo pedido, ou o tempo passar, cancela a proposta pendente.

Testado de ponta a ponta no seu PC, com o Claude de verdade: ler a agenda, uma ação fora da pasta barrada até o toque em Confirmar, e executada depois dele.

### Interruptor geral e registro
- **Botão "Ações liberadas"** no topo do app (aparece no modo completo): um toque, com confirmação, volta o celular para `consulta` na hora. O app **só reduz** o acesso; religar o completo é só pelo PC.
- **Bandeja do PC:** "Celular: ações liberadas" liga e desliga o modo completo na hora.
- **Atividade** (ícone de relógio no app): cada pedido, resposta, confirmação, ferramenta usada e troca de acesso, gravados só no PC em `.estado/celular_auditoria.jsonl` (fora do git; guarda até ~2 MB).
- Se o celular for perdido: desligue as ações na bandeja do PC, troque o token (apague `celular.token`, rode `python jarvis.py --celular-token` e reinicie) e remova o aparelho no Tailscale.

## Limites
- O **PC precisa estar ligado**, com internet e com o Jarvis rodando; o celular o alcança pelo Tailscale.
- No modo `completo` o Claude fica aberto por 10 minutos parado (`idle_minutes`), para guardar a proposta que espera o seu toque, e usa um pouco mais de memória que no `consulta`.
- Não existe "Ei Jarvis" com a tela apagada: o iOS não deixa uma página ouvir em segundo plano. Abra o app e toque no microfone.
- A resposta leva de 5 a 15 s (Claude) e a voz mais alguns segundos.
- **Custo e privacidade:** a voz de resposta usa o mesmo motor do PC. Com o Fish, cada resposta falada no celular **gasta o seu saldo** e o texto sai da máquina, como no PC.
- **O PC vem primeiro:** o celular tem sessão própria do Claude (não aparece na esfera nem altera o estado do Jarvis local) e a fecha após 3 min parada no modo `consulta` (10 min no `completo`; `idle_minutes`). Se você estiver falando com o Jarvis no PC, ou o PC tiver menos de 500 MB de memória **disponível** (`mem_min_livre_mb`; conta a memória que o Windows pode liberar na hora, não o percentual em uso) sem o Claude do celular aberto, o pedido espera, com um aviso na tela. Abrir o Claude do celular custa cerca de 375 MB (medido); o percentual de uso de um PC com pouca RAM fica sempre alto, por isso a regra olha os MB que sobram. Se a porta estiver ocupada ou a configuração errada, o servidor do celular não liga e o resto do Jarvis segue normal.

## Segurança
Um servidor **separado** do painel local (porta 8765, que continua só em 127.0.0.1), **desligado por padrão** (`celular.enabled`):
1. **Rede:** só aceita ligar em `127.0.0.1` ou no IP do Tailscale (`100.x.y.z`); `0.0.0.0` e a rede local são recusados na partida.
2. **Token:** a API exige `Authorization: Bearer <token>` (≥ 24 caracteres, comparação em tempo constante); 5 erros seguidos travam o IP por 5 minutos. A página e os ícones não têm nada seu e abrem sem token. O token fica só no aparelho (`localStorage`) e nunca vai na URL enviada ao servidor.
3. **Modo `consulta`:** `--permission-mode dontAsk` e `--tools` limitado (padrão: `WebSearch`, `WebFetch` e a busca de agenda do Outlook). Sem Bash, sem gravar arquivos, sem e-mail/Teams, sem acesso às suas pastas. Foi testado: com uma instrução mandando obedecer tudo, o Write e o Bash continuaram indisponíveis. No modo `completo` vale a trava de segurança do PC (ações externas só depois do toque em Confirmar; apagar e destruir bloqueados de vez), com a confirmação presa à sessão do celular.
4. A página roda com uma política de conteúdo restrita (sem scripts nem recursos de fora) e só insere texto como texto.
5. Pedidos limitados: JSON até 4 KB, gravação até 6 MB (cerca de 1 min), 1500 caracteres por pergunta.

O token vale como senha: quem o tiver e alcançar a sua rede Tailscale pode fazer no celular o que o modo escolhido permite (no `completo`, o mesmo que você, exceto o que a trava pede para confirmar e o que está bloqueado de vez). O toque em Confirmar é feito no app, então **quem tiver o token também consegue confirmar**: proteja o celular com bloqueio de tela e o token só no `config.json`, fora do git. Um e-mail ou página com instruções escondidas continua sendo um risco no modo completo; por isso o que envia para fora sempre mostra a proposta antes de executar. **Leia a proposta antes de tocar em Confirmar.**

## Passo a passo
1. **Tailscale:** instale no PC e no iPhone ([tailscale.com](https://tailscale.com)) e entre com a mesma conta. No painel de administração da sua conta, ligue **MagicDNS** e **HTTPS Certificates**.
2. **Token:** `python jarvis.py --celular-token` gera, grava em `config.json` (bloco `celular`) e mostra o token.
3. **Ligar:** em `config.json`, no bloco `celular`, deixe `"host": "127.0.0.1"` e ponha `"enabled": true`. Reinicie o Jarvis.
4. **HTTPS (o microfone do navegador só funciona em HTTPS):** no PC, `tailscale serve --bg 8767` (a sintaxe pode variar com a versão; veja `tailscale serve --help`). O endereço será `https://<nome-do-pc>.<sua-rede>.ts.net`; `tailscale serve status` mostra.
5. **Instalar no iPhone** (Tailscale ligado): no Safari, abra `https://<nome-do-pc>.<sua-rede>.ts.net/#t=<token>`. A página guarda o token e o tira da barra de endereço. Depois: **Compartilhar → Adicionar à Tela de Início**. (Sem o `#t=`, a página pede o token na primeira vez.)
6. Abra o ícone, toque no microfone, libere o acesso ao microfone e fale. Termina sozinho ao ficar em silêncio.

Sem HTTPS (por exemplo, `host` = IP do Tailscale e `http://100.x.y.z:8767`) tudo funciona **menos o microfone**; o texto e as tarefas seguem normais.

## Tarefas por voz no celular
Na aba **Conversa** (microfone ou texto) as tarefas são tratadas na hora pelo próprio Jarvis, sem passar pelo Claude:
- **Anotar:** "anote tarefa comprar café", "nova tarefa comprar café", "inclua uma tarefa...", "adicione a tarefa...", "anota aí..."; com data: "anote tarefa ligar para o contador **para amanhã**" (a data precisa vir com "para" ou "até": hoje, amanhã, sexta, 25/12...). **Sem data, a tarefa entra sem data e o Jarvis não pergunta "para quando?"**.
- **Concluir:** "conclua a tarefa 2", "marque a tarefa 1 como concluída", "dê como concluída a tarefa do boleto", "já fiz a tarefa do contador", "tarefa 1 concluída". O número é a posição na lista de abertas; também vale um trecho do nome.
- **Listar:** "quais são as minhas tarefas".
- **Só no PC:** remover e desfazer (o celular responde que isso é no computador).

## Widget na tela inicial do iPhone (tarefas)
Widget nativo do iOS exige um app nativo feito num Mac. Sem isso, o caminho é o app gratuito **Scriptable**, que roda um pequeno script como widget. O script está em [docs/widget/jarvis-tarefas.js](widget/jarvis-tarefas.js): lista as próximas tarefas (abertas, com prazo, vencidas em vermelho) e, sem conexão, mostra o último dado salvo com um aviso.

1. Instale o **Scriptable** na App Store (gratuito).
2. No Scriptable, toque em **+** e cole o conteúdo de `jarvis-tarefas.js` (dá para abrir o arquivo no GitHub, copiar e colar). Dê o nome **Jarvis Tarefas**.
3. Toque em **Play** dentro do app: ele pede o **endereço** (`https://<nome-do-pc>.<sua-rede>.ts.net`) e o **token**, e guarda os dois no Keychain do iPhone (nada fica no arquivo).
4. Na tela inicial, segure num espaço vazio, toque em **+**, escolha **Scriptable**, o tamanho (pequeno mostra 3 tarefas, médio 4, grande 9) e depois toque no widget para escolher o script **Jarvis Tarefas**.

O iOS decide a frequência de atualização (o script pede a cada 15 min, mas pode demorar mais). O widget só funciona com o **Tailscale ligado** no iPhone. Tocar nele abre o Jarvis no navegador. Ele só lê `GET /api/tarefas`: não conversa com o Claude nem altera nada.

## Pontos não verificados
- Testado em ponta a ponta no navegador do computador (login, texto, voz de resposta, tarefas, gravação com fim automático, erros) e a gravação real do navegador foi decodificada com sucesso pelo PC. **Não testado no iPhone nem no Android**: o Safari do iOS tem regras próprias (permissão do microfone, liberação do áudio por toque). Teste e me diga o que falhar.
- O **widget Scriptable** foi testado só com uma simulação da API do Scriptable (lógica de tarefas, cache, erros, tamanhos), não no iPhone: o visual e o comportamento de atualização do iOS podem exigir ajustes.
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
| `mem_min_livre_mb` | Com menos MB de memória disponível que isso, o celular espera (padrão 500; `0` tira o limite) |
| `mem_max_pct` | Opcional: também espera acima deste uso percentual da memória (não definido por padrão) |

Teste sem rede: `python jarvis.py --celular-texto "que dia é hoje?"`.
