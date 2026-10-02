# network_proxy

## Правила работы с сетью и серверами:
- **Вся внешняя сеть и удаленный сервер VPS (195.133.5.32, agrita.ru, stage.agrita.ru) доступны СТРОГО через SOCKS5-прокси**:
  - `ALL_PROXY=socks5h://127.0.0.1:1080`
  - `HTTPS_PROXY=socks5h://127.0.0.1:1080`
  - `HTTP_PROXY=socks5h://127.0.0.1:1080`
- **Прямые соединения (без прокси) ЗАПРЕЩЕНЫ**: они приводят к сетевому таймауту.
- **SSH и Rsync**:
  - В файле `~/.ssh/config` всегда должна присутствовать директива:
    ```sshconfig
    Host 195.133.5.32 agrita.ru stage.agrita.ru
        ProxyCommand nc -X 5 -x 127.0.0.1:1080 %h %p
        ServerAliveInterval 30
        ServerAliveCountMax 3
    ```
- **Скрипты на Python (Paramiko)**:
  - При подключении к VPS через `paramiko` обязательно передавать сокет-прокси:
    ```python
    proxy = paramiko.ProxyCommand("nc -X 5 -x 127.0.0.1:1080 195.133.5.32 22")
    ssh.connect(HOST, 22, username=..., password=..., sock=proxy, timeout=30)
    ```
- **HTTP/cURL запросы**:
  - Инструменты curl/requests/urllib должны использовать прокси 127.0.0.1:1080.
