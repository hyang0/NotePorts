
# NotePorts - Windows 端口监控工具

一个windows端口监控和可视化工具，帮助您轻松管理和监控windows服务器上的端口使用情况。

访问应用：

打开浏览器访问 `http://localhost:7577`

![](./img/screenshot.png)


### 本地开发

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 运行应用：
```bash
# 使用默认端口7577
python app.py

# 使用自定义端口
python app.py --port 8080

```

## 🔧 技术架构

- **后端**: Python Flask + psutil



## 🔧 配置说明

### 命令行参数

NotePorts 支持以下命令行参数来自定义运行配置：

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `--port` | `-p` | 7577 | Web服务端口 |
| `--host` | 无 | 0.0.0.0 | Web服务监听地址 |

**使用示例：**
```bash
pip install -r requirements.txt
python app.py -h

usage: app.py [-h] [--port PORT] [--host HOST] [--debug]

NotePorts - Windows Port Monitor

options:
  -h, --help       show this help message and exit
  --port, -p PORT  Web Port (default: 7577)
  --host HOST      Listen Address (default: 0.0.0.0)
  --debug          Debug Mode


# 修改端口以避免冲突
python app.py --port 8080

```

---

**NotePorts** - 让端口管理变得简单高效！ 🚀
