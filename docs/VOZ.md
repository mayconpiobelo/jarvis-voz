# Voz

## Configuração atual
Kokoro (`kokoro-onnx`), local e gratuito, em português do Brasil. Ajuste em `config.json`:

| Chave | O que faz |
|---|---|
| `kokoro_voice` | Uma voz (`pm_alex`, `pm_santa`, `pf_dora`) ou **mistura**: `"pm_alex:0.8,bm_george:0.2"` (pesos somam 1) |
| `kokoro_speed` | Ritmo (0,5–2,0) |
| `kokoro_pitch` | Tom: abaixo de 1 = mais grave (reamostragem) |
| `kokoro_warmth` | Reforço de graves |
| `kokoro_reverb` | Ambiência curta (efeito “IA”) |
| `kokoro_pause_ms` | Pausa depois de cada frase |

A fala é gerada frase a frase (a próxima é gerada enquanto a atual toca) e frases longas são quebradas em `;` `:` `,` para começar mais cedo.

## Voz da Microsoft (Edge TTS) — opcional, em nuvem
Com `"tts_engine": "edge"` o Jarvis fala com a voz neural `pt-BR-AntonioNeural` (gratuita, sem chave; pacote `edge-tts`). É a voz usada pelo projeto de referência jgm-source/jarvis-opensource, sem nenhum ajuste de tom ou efeito.

| Chave | O que faz |
|---|---|
| `tts_engine` | `"edge"` liga essa voz; `"kokoro"` volta à voz local; `"sapi"` usa a voz do Windows |
| `edge_voice` | `pt-BR-AntonioNeural` (padrão), `pt-BR-FranciscaNeural`, `pt-BR-ThalitaNeural`… |

**Privacidade:** diferente do Kokoro, cada frase falada **é enviada aos servidores da Microsoft** para virar áudio. Isso inclui o que o Claude responde (tarefas, agenda, nomes). Para o que for sensível, mantenha o Kokoro.

**Falhas:** o serviço às vezes não devolve áudio ou devolve o áudio **cortado** sem avisar. O Jarvis tenta de novo até 3 vezes por frase e descarta áudio curto demais para o texto. Se ainda assim não responder (sem internet, por exemplo), fala com o Kokoro e deixa o Edge de lado por 60 s. As chaves `kokoro_*` (tom, calor, ambiência) não se aplicam à voz Edge.

## Fish Audio — opcional, em nuvem e **paga**
Com `"tts_engine": "fish"` o Jarvis fala pela API do [Fish Audio](https://fish.audio): uma voz da biblioteca ou **uma voz clonada sua**. É cobrado por uso (cerca de US$ 15 por milhão de bytes de texto nos modelos `s2-pro`/`s2.1-pro`, [preços oficiais](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits); confira antes de usar), sem mensalidade.

1. Crie a conta e uma chave de API no site do Fish Audio e coloque crédito.
2. No `config.json` (fora do git) preencha:

| Chave | O que faz |
|---|---|
| `tts_engine` | `"fish"` |
| `fish_api_key` | Sua chave. Alternativa: variável de ambiente `FISH_API_KEY` |
| `fish_voice_id` | ID de 32 caracteres da voz ou a URL da página dela (`fish.audio/m/<id>`). Vazio = voz padrão do Fish |
| `fish_model` | `s2-pro` (padrão). O `s1` sai de operação em 31/12/2026 |
| `fish_model_gratis` | Modelo sem custo usado quando o pago falha ou o saldo acaba (`s2.1-pro-free`); vazio desliga |
| `fish_speed` / `fish_speed_gratis` | Velocidade da fala de cada modelo (0,5–2,0; 1 = normal). O gratuito fala ~4% mais rápido que o pago (medido: 20,0 contra 19,2 letras/s); `0.97` iguala o ritmo (19,0) e o padrão `0.94` o deixa um pouco mais calmo (18,6) |

**Voz sugerida:** o `config.example.json` já traz `fish_voice_id` com a voz pública “Jarvis” (`5566fffe8b8046bc85e576aa9813b9bd`), em português, de timbre masculino maduro e tom formal de mordomo — é a voz que o autor usa. **Ela foi criada por outro usuário do Fish Audio, sem licença declarada, e não sabemos de quem é a gravação original:** confira a página dela no Fish antes de usar, não a use comercialmente e troque por uma voz sua ou licenciada se preferir. O autor dela pode apagá-la ou torná-la privada a qualquer momento (o Jarvis então fala com a voz reserva).

**Atenção sobre a chave do exemplo:** o `config.example.json` traz a chave de API **do autor** em `fish_api_key`, publicada por decisão dele para quem quiser testar a voz. Ela é paga e pode ser esgotada, revogada ou trocada a qualquer momento (o Jarvis então cai no modelo gratuito, no Edge e no Kokoro). **Para uso contínuo, crie a sua própria chave e coloque no seu `config.json`**; não dependa da do autor.

3. Teste sem gastar o Claude: `python jarvis.py --dizer "Perfeitamente, senhor."`

**Privacidade e custo:** cada frase falada **sai da máquina** e é cobrada. **Nunca coloque a chave em arquivo versionado.** Use só voz sua ou licenciada: clonar a voz de uma pessoa real (por exemplo um ator de dublagem) exige a autorização dela.

**Cadeia de voz:** Fish pago (`fish_model`) → **Fish gratuito, com a mesma voz** (`fish_model_gratis`, padrão `s2.1-pro-free`, preço US$ 0 na [tabela oficial](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits); mais lento, uns 3 s por frase, e a tabela não detalha limites de uso; vazio desliga) → Edge → Kokoro.
- Se o Fish pago falhar por um motivo qualquer, o Jarvis tenta o gratuito e, depois, as reservas por 60 s.
- Se o saldo acabar, ele passa a falar pelo modelo gratuito (mesma voz) e só tenta o pago de novo depois de 1 hora (tempo para você recarregar o saldo; reiniciar o Jarvis tenta na hora).
- Se a chave for recusada, nenhum dos dois modelos do Fish é tentado por 1 hora, e vão direto o Edge e o Kokoro. A chave e a resposta do servidor nunca vão para o `jarvis.log`.

## Vozes reserva parecidas com a do Fish
Quando o Fish falha ou o saldo acaba, o Jarvis fala com o Edge e, se ele também falhar, com o Kokoro. Para a troca ser pouco perceptível, as reservas foram **calibradas com medições** (tom, ritmo, pausas e brilho) em 6 frases, contra a voz sugerida do Fish. Média das 6 frases:

| | Tom (F0) | Letras/s | Pausas | Centroide | Graves (< 500 Hz) |
|---|---|---|---|---|---|
| Fish (alvo) | 143 Hz | 19,2 | 11% | 592 Hz | 77,6% |
| Edge `+10%` / `+6Hz` | 144 Hz | 19,2 | 15% | 601 Hz | 75,5% |
| Kokoro (receita abaixo) | 144 Hz | 19,2 | 17% | 580 Hz | 75% |

- **Edge:** `edge_rate: "+10%"`, `edge_pitch: "+6Hz"` (aceitam `+N%` e `+NHz`, também negativos) e `reserva_pausa_max_ms: 100` (encurta qualquer silêncio das vozes reserva para no máximo 100 ms; `0` desliga).
- **Kokoro** (receita medida, não é o padrão do exemplo): `kokoro_voice: "pm_alex:0.5,pm_santa:0.5"`, `kokoro_speed: 1.113`, `kokoro_pitch: 1.06`, `kokoro_warmth: 0.3`, `kokoro_reverb: 0`, `kokoro_pause_ms: 60`. O `kokoro_presence` (realce acima de ~600 Hz, padrão 0) existe para deixar a voz menos abafada.

São métricas objetivas: o timbre em si (a “cara” da voz) não dá para copiar com ajustes de tom e ritmo. Ouça e ajuste se quiser.

## Laboratório de voz
`python voz_lab.py` → `http://127.0.0.1:8766`: cartões com opções, botão ▶, ajuste fino e um painel que mostra os valores prontos para colar no `config.json`.

## Não existe voz britânica em português
O Kokoro tem vozes britânicas só em inglês; misturar uma pequena parte altera o timbre, mas a pronúncia continua brasileira. **Não clone a voz de pessoas reais sem autorização**; para uma voz própria, use uma voz sua/licenciada.

## Alternativas avaliadas (GitHub, 11/2026)
| Opção | Português do Brasil | Observação |
|---|---|---|
| **Kokoro** (usada) | sim (3 vozes) | 82M, CPU, rápida |
| **Chatterbox** (MIT) | sim, modelo dedicado `pt-br` | **Medido**: em um notebook com GPU de 4 GB só cabe em fp16 (pico 2,5 GB) e gera 2,45× mais lento que o tempo real (5–10 s por frase); em fp32 estoura a memória de vídeo (RTF 16). Não serve para conversa ao vivo nessa classe de hardware; serviria para frases fixas pré-geradas |
| VoxCPM2 (Apache) | sim (30 idiomas) | 2B parâmetros, pesado para 4 GB; recurso interessante: criar voz por descrição |
| MOSS-TTS-Nano (Apache) | listado, variante não esclarecida | 100M, tempo real em CPU; qualidade não avaliada |
| Piper | 4 vozes pt_BR | muito leve, mais robótico (GPL-3.0) |
| Nuvem (ElevenLabs, OpenAI, Azure) | sim | melhor qualidade, mas o texto das respostas sai da máquina |

Dependências do Chatterbox que encontramos ao testá-lo: o pacote do PyPI (0.1.7) é mais antigo que o código do GitHub (use o GitHub para o modelo `pt-br`); o decodificador V3 não traz dois buffers constantes do tokenizador (carregue com `strict=False` **verificando** que só eles faltam); o marcador d’água Perth precisa de `setuptools<81` e deve permanecer ligado.
