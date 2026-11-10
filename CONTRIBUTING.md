# Contribuir

Abra uma issue descrevendo o problema ou a alteração desejada. Para erros, inclua distribuição, versão do GNOME Shell, extensão de dock, GPU/driver, passos de reprodução e comportamento observado.

## Desenvolvimento

Instale as dependências descritas no README e execute os testes a partir de um checkout limpo.

```sh
make check
```

Mantenha as leituras reais e o tratamento de sensores ausentes. Alterações na coleta devem preservar snapshots atômicos, histórico limitado e instância única. Alterações na integração gráfica precisam encerrar timers, monitores de arquivo e conexões ao desativar a extensão.

Para mudanças visuais, valide clique, segundo clique, Esc, clique fora e atualização do tooltip com o ponteiro parado. Inclua uma captura recortada da interface e descreva o ambiente de teste.

## Pull requests

Explique o problema, a mudança de comportamento e a validação realizada. Inclua um teste quando ele detectar uma regressão específica. Registre as plataformas ou sensores que ainda precisam de validação física.

Os testes gráficos opcionais são descritos em `docs/TESTING.md`. Eles interagem com a sessão desktop atual.
