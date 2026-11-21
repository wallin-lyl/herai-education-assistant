# HerAI 智能教育助手

HerAI 是面向大学生学习场景的 Flutter 应用，使用 FastAPI 代理国内免费模型，
提供连续对话、流式回答、女性榜样资料、学习计划、学习资料和个人学习统计。

## 当前功能

- AI 学习助手：连续对话、SSE 流式显示、停止生成、重新生成、清空对话、本地历史恢复。
- 多会话记录：新建、切换、自动命名、重命名和删除不同学习主题的对话。
- 网络稳定性：首字与空闲超时、503/429/鉴权/模型错误分类、有限自动重试，不自动切换付费模型。
- 默认模型：智谱 `GLM-4.7-Flash`，官方文档标记为免费文本模型；DeepSeek 官方 API 为按量计费，因此未作为免费默认。
- 免费额度保护：限制单客户端每分钟请求数，并限制同时生成中的回答数量。
- 女性榜样资源库：科学家、教育家、工程师分类，搜索、人物详情与可信资料说明。
- 学习计划：创建、编辑、删除任务，设置科目、日期、优先级和完成状态。
- 学习资料：分类、搜索、收藏、详情、个人笔记创建与删除。
- 资料步骤可直接生成预填学习任务，保存后自动进入学习计划。
- 个人中心：昵称和简介编辑、学习统计、提醒偏好、AI 服务检查、隐私说明与数据清除。
- 数据迁移：把全部个人资料、对话、任务、笔记和收藏复制为 JSON 备份，并可从剪贴板校验恢复。
- 响应式界面：桌面侧栏和移动端底部导航共用同一套六个功能模块。

## 本地运行

最简单的启动方式：双击项目根目录的 `启动HerAI-本机.cmd`；同一 Wi-Fi 下给其他人
试用时双击 `启动HerAI-局域网测试.cmd`，再把终端打印的网址发给对方。

### 1. 后端

首次在新环境安装 Python 依赖时执行：

```powershell
cd D:\HerAI_Project\herai\bankend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

将 `bankend/.env.example` 中需要的配置写入已有的 `bankend/.env`。至少需要：

```dotenv
AI_PROVIDER=zhipu
ZHIPU_API_KEY=你的智谱免费接口密钥
ZHIPU_MODEL=glm-4.7-flash
MAX_CONCURRENT_CHATS=1
RATE_LIMIT_PER_MINUTE=20
```

启动后端：

```powershell
cd D:\HerAI_Project\herai\bankend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

也可以直接在 VS Code 的“终端 → 运行任务”中选择 `HerAI: 启动后端`。

检查服务：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

### 2. Flutter

```powershell
cd D:\HerAI_Project\herai
flutter pub get
flutter run -d chrome
```

Windows、Web 和 iOS 模拟器默认访问 `http://127.0.0.1:8000`。
Android 模拟器中的电脑主机地址是 `10.0.2.2`，可这样运行：

```powershell
flutter run -d emulator-5554 --dart-define=HERAI_API_BASE_URL=http://10.0.2.2:8000
```

Android 模拟器已默认使用 `10.0.2.2`。真机调试或部署时，也可以在
“个人中心 → 后端服务地址”中直接填写电脑的局域网 IP 或 HTTPS 服务地址，
无需重新编译；编译时仍可使用 `--dart-define=HERAI_API_BASE_URL=...` 指定默认值。
仅在你信任的网络中临时调整 Uvicorn 监听地址，不要把本地后端直接暴露到公网。

## 测试

```powershell
flutter analyze
flutter test
flutter build web
```

后端语法检查：

```powershell
cd bankend
python -m py_compile main.py config.py schemas.py ai_common.py zhipu_service.py
```

## 费用与密钥约束

- 应用不会开通任何平台计费、绑定银行卡或自动充值。
- 后端固定使用配置的智谱免费模型，不在 429/503 时自动切换到付费模型。
- AI API Key 只从 `bankend/.env` 读取，不进入 Flutter 代码或前端构建产物。
- `.env`、备份和 Python 缓存已加入 `.gitignore`。
- 免费模型和服务可用性由智谱平台与官方政策决定；限流时应用会显示错误并保留用户问题。

## 数据存储

个人资料、聊天记录、学习任务、自定义笔记、收藏和学习日期使用
`SharedPreferences` 保存在当前设备。清除浏览器站点数据或卸载应用会删除这些数据；
可先在个人中心导出 JSON 备份并通过剪贴板恢复。
当前未实现账号云同步，也未接入文件上传；资料模型已预留个人创建、来源和后续附件扩展字段。

## 云端部署

项目根目录提供 `Dockerfile` 和 `render.yaml`，FastAPI 会同时提供 Web 页面和 AI 接口。
云端部署后不再依赖本机开机；配置 `GEMINI_API_KEY` 环境变量即可。`render.yaml`
只使用免费方案，不包含自动付费配置。免费平台可能休眠或限制运行时长。

## 代码结构

```text
lib/
  data/          内置人物与学习资料
  models/        多会话聊天、任务、资料和人物模型
  screens/       六个功能模块与响应式主导航
  services/      AI SSE 客户端与本地存储封装
  state/         应用级持久化状态
  widgets/       共享界面组件
bankend/
  main.py        FastAPI 路由与 SSE 协议
  zhipu_service.py   智谱免费模型请求、流式解析、重试和错误映射
  gemini_service.py  可选旧版 Gemini 适配
  schemas.py     请求校验
  config.py      环境配置
```

接手前的关键文件备份位于 `_backups/pre_development_20261121_215651`。
备份刻意不包含 `.env` 或任何密钥。
