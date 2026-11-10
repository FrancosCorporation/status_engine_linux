# Validação

## Testes automatizados

```sh
make check
```

A suíte contém 13 testes de referência e do coletor C. Os fixtures isolam `/proc`, sysfs e configurações em diretórios temporários. A CI executa a compilação com avisos tratados como erros e a suíte Python.

## Validação gráfica registrada

A versão inicial foi exercitada em Ubuntu 26.04.1, GNOME Shell 50.1 e Wayland, com Ubuntu Dock e GPU AMD Navi 22 usando amdgpu.

| Comportamento | Resultado observado |
|---|---|
| Ícone na dock inferior | Disponível como um único favorito |
| Primeiro clique | Abre o painel |
| Segundo clique | Fecha o painel |
| Esc e clique fora | Fecham o painel |
| Coleta com painel fechado | Sequência de snapshots continua aumentando |
| Ponteiro parado sobre o ícone | Quatro atualizações consecutivas do resumo verificadas |
| Aberturas repetidas | 15 ciclos completos passaram |
| Preferências | Abertura pelo painel e salvamento GTK4 verificados |
| Configurações ao vivo | Intervalo, métricas, porcentagens, minigráficos, aparência e históricos verificados |
| Temperaturas | CPU package e GPU edge comparados com hwmon |
| Coletor | Uma instância ativa e encerramento por SIGTERM verificados |

Os valores instantâneos de CPU, memória e temperaturas podem variar entre leituras próximas. Os testes de fixtures verificam a aritmética exata. O cenário de validação manteve as cargas de trabalho existentes na máquina.

## Desempenho observado

Durante 30 segundos, o coletor nativo usou aproximadamente 0,10% de um núcleo. O RSS passou de 2.648 para 2.708 KiB enquanto o histórico era preenchido. O custo incremental da interface dentro do GNOME Shell ainda precisa de medição isolada.

Para medir o serviço instalado na sua máquina, execute o diagnóstico opcional.

```sh
/usr/bin/python3 tests/performance.py
```

Os relatórios locais são escritos em `evidence/`.

## Repetir os testes gráficos

Os módulos `tests/desktop-checks.js` e `tests/configuration-checks.js` executam dentro do GNOME Shell, pelo Looking Glass. O primeiro cria dispositivos virtuais de ponteiro e teclado, movimenta o cursor, abre e fecha o painel e grava capturas. O segundo altera preferências para validar sua aplicação e restaura o arquivo original.

Na sessão de teste, abra o Looking Glass pelo diálogo Alt+F2, usando `lg`. No console, importe o módulo pelo caminho absoluto do seu checkout.

```js
(await import('file:///caminho/absoluto/status_engine_linux/tests/desktop-checks.js')).run()
```

Execute essa validação em uma sessão disponível para automação de ponteiro e teclado. Atividade simultânea no desktop pode interferir nos eventos. As capturas completas permanecem no diretório local `evidence/`.

`tests/desktop.py` é um auxiliar opcional que usa `ydotool`, `xclip` e `wl-clipboard`. Ele exige que esses programas estejam instalados e que o teclado virtual tenha acesso à sessão. Os testes de salvamento GTK4 e de comparação de sensores podem ser executados individualmente.

```sh
/usr/bin/python3 tests/preferences-save.py
/usr/bin/python3 tests/hardware.py
```

## Validações pendentes

O início automático em novo login, observação de estabilidade por horas, múltiplas GPUs físicas, temperaturas AMD de CPU e outras escalas de tela precisam de validação adicional. A suíte automatizada valida os formatos e o comportamento com sensores ausentes.
