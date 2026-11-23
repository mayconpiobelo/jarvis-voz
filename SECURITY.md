# Política de segurança

Este projeto dá a um agente de IA acesso amplo ao computador do usuário. Leve a sério qualquer falha que permita **executar ações sem a confirmação por voz**, contornar o bloqueio permanente ou expor o servidor local a outros sites.

## Como reportar
**Não abra uma issue pública.** Avise o(s) mantenedor(es) diretamente (por exemplo, pelo recurso “Report a vulnerability” do GitHub, se estiver habilitado no repositório) com: passos para reproduzir, versão/commit, e o impacto que você observou.

## O que está no escopo
- `trava.py` deixando passar ferramenta que deveria pedir confirmação ou ser bloqueada.
- Servidor local (`127.0.0.1:8765`) acessível por outra origem ou via DNS rebinding.
- Vazamento de dados pessoais ou segredos para o repositório ou para logs.

Modelo de ameaças, camadas de defesa e riscos residuais: [docs/SEGURANCA.md](docs/SEGURANCA.md).
