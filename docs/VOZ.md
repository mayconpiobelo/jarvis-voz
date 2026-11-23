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
