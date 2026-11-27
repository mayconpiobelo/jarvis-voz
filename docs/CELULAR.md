# Jarvis no celular

Um app web instalável (PWA) que o próprio Jarvis serve. Você o abre no Safari do iPhone (ou no Chrome do Android), escolhe **Adicionar à Tela de Início** e ele vira um ícone. Tem três abas, no mesmo visual de vidro e degradê do painel do PC: **Conversa** (esfera, voz pelo microfone ou texto), **Painel** (cartões com o clima da sua cidade, a CPU e a memória do PC, o consumo do Claude com a hora em que reinicia, um resumo das tarefas e a música que toca no PC) e **Tarefas** (ver, anotar, concluir). A resposta volta **na mesma voz do PC** (Fish → Edge → Kokoro, com as mesmas reservas).

> **Escopo:** no celular o Jarvis só **consulta** (web e agenda) e cuida das **tarefas**: ver, anotar e concluir. Não envia e-mail ou mensagem, não liga, não grava nem apaga arquivos, e remover/desfazer tarefa só pelo PC. Isso é de propósito: o Jarvis do PC roda com acesso amplo, e um celular perdido ou um token vazado não pode ter esse poder.

## Limites
- O **PC precisa estar ligado**, com internet e com o Jarvis rodando; o celular o alcança pelo Tailscale.
- Não existe "Ei Jarvis" com a tela apagada: o iOS não deixa uma página ouvir em segundo plano. Abra o app e toque no microfone.
- A resposta leva de 5 a 15 s (Claude) e a voz mais alguns segundos.
- **Custo e privacidade:** a voz de resposta usa o mesmo motor do PC. Com o Fish, cada resposta falada no celular **gasta o seu saldo** e o texto sai da máquina, como no PC.
- **O PC vem primeiro:** o celular tem sessão própria do Claude (não aparece na esfera nem altera o estado do Jarvis local) e a fecha após 3 min parada (`idle_minutes`). Se você estiver falando com o Jarvis no PC, ou o PC tiver menos de 500 MB de memória **disponível** (`mem_min_livre_mb`; conta a memória que o Windows pode liberar na hora, não o percentual em uso) sem o Claude do celular aberto, o pedido espera, com um aviso na tela. Abrir o Claude do celular custa cerca de 375 MB (medido); o percentual de uso de um PC com pouca RAM fica sempre alto, por isso a regra olha os MB que sobram. Se a porta estiver ocupada ou a configuração errada, o servidor do celular não liga e o resto do Jarvis segue normal.

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
