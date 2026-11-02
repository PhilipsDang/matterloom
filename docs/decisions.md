# 第一阶段实施决策

日期：2026-11-01。

## 本阶段目标

对应项目计划 11/2–11/8：准备仓库和样本，实现多文件上传、解析状态、按页查看 PDF 原文，为后续原文引用建立可靠基础。

本阶段只处理事项、文档与原文单元。页面不展示尚未实现的问答、事实抽取或摘要能力。

## 与初始技术建议的差异

初始建议为 Streamlit 和 Docling。本次环境没有这两个依赖，安装尝试未成功。为推进可独立验证的工作，先用已有组件完成本地实现：

| 部分 | 当前实现 | 后续边界 |
|---|---|---|
| 界面 | 原生 HTML/CSS/JavaScript | 保留中文、事项内范围、可核对原文等产品约定 |
| 服务 | Python 标准库 HTTP 服务 | 只用于单用户本机原型，后续再决定是否迁移框架 |
| PDF 文字 | pypdf | 暂不承诺复杂表格结构和全版面识别 |
| PDF 页面 | pypdfium2 | 输出真实页面图像，渲染调用加锁 |
| Word | python-docx | 保留正文段落和表格坐标，不伪造页码 |
| 扫描识别 | 可选 Apple Vision 适配器 | 当前环境实际调用失败；保留可替换接口与失败提示 |
| 保存 | SQLite 和本地原件 | 数据在 data/，运行生成内容不纳入版本库 |

这些差异是当前可执行方案，不表示已完成对 Docling 与其他引擎的准确率比较。没有安装未验证的 Docling 占位代码。

## 原文保存规则

- 每次上传保存原始字节，不改写原件。
- 使用随机文档编号作为磁盘文件名；显示名称与存储路径分离。
- 使用 SHA-256 在单一事项中识别完全相同的文件。
- PDF 原文单元携带文件页序号；DOCX 单元携带段落或表格坐标。
- 单元编号由文档编号和顺序号组成；原件不变时重新解析保持相同编号。未来采用不同切分器时需要额外引入解析版本。
- 解析失败的原件继续保留；一个失败文件不会阻断其他文件。

## 尚未完成的阶段验收

初次工具环境拒绝 Git 初始化和监听本地端口。后续检查已发现本地 main 分支仓库，尚无提交；真实浏览器操作仍未验证。用户在自己的终端启动后，继续执行 verification.md 中的手动检查。

## 技术文档参考

- [Streamlit 多文件上传](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader)
- [Docling 安装](https://docling-project.github.io/docling/getting_started/installation/)
- [Apple Vision 文字识别](https://developer.apple.com/documentation/vision/recognizing-text-in-images)

文档用于评估与实现参考；本项目的验证结果以实际测试记录为准。
