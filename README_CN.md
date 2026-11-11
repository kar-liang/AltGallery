> **⚠️ 本项目基于 [bebound/AltGallery](https://github.com/bebound/AltGallery) 修改而来，原作者是 [Hang (@bebound)](https://github.com/bebound)，遵循 MIT 许可证。**
>
> 原项目是面向所有人的通用软件源（60+ 个 app）。**这份是我个人的精简版**，只保留自己需要的 20 个。
> 想要完整的请直接去[原仓库](https://github.com/bebound/AltGallery)。
>
> 生成工具用的是作者的 [AltGen](https://github.com/bebound/AltGen)，本项目未改。

<h1 align="center">AltGallery · 个人自用源</h1>

<p align="center"><b>简体中文</b> | <a href="README.md">English</a></p>

## 添加源

<p align="center">
<a href="https://altdirect.app/?url=https://raw.githubusercontent.com/kar-liang/AltGallery/master/all-apps.json" target="_blank">
<img src="assets/add-alt-source.png" alt="Add AltSource" width="200">
</a>
</p>

<p align="center">点图片添加，或手动填：</p>

```
https://raw.githubusercontent.com/kar-liang/AltGallery/master/all-apps.json
```

<p align="center">无法直连 <code>github.com</code>？用加速版（图片和 ipa 全走 gh-proxy）：</p>

```
https://raw.githubusercontent.com/kar-liang/AltGallery/master/all-apps-proxy.json
```

可用于 [AltStore](https://github.com/altstoreio/Altstore)、[SideStore](https://github.com/SideStore/SideStore)、[LiveContainer](https://github.com/LiveContainer/LiveContainer)、[Feather](https://github.com/claration/Feather) 等兼容应用。

## 包含的 app

| 侧载工具 | 视频 / 番剧 | 音乐 | 漫画 / 阅读 |
|---|---|---|---|
| iPadn | AniBaka | Kumone | Aidoku |
| MiniWatts | AnimeFlow | MeloX | Breeze |
| AirCard-iOS | Animeko | | EhPanda |
| | PiliPlus | | Mangayomi |
| | PureLive | | Pixiv-SwiftUI |
| | Opaline | | |

| 社交 / 论坛 | 其他 |
|---|---|
| TiebaPure | 酷安（非官方桌面版移植） |
| ZhihuMinusMinus | WQ Files（需 iOS 26+） |

共 20 个，约 474 MB。单个 app 的独立源在 `apps/<名称>/apps.json`。

## 怎么加新 app

三种方式，按省事排序：

1. **给 QQ 机器人发 GitHub 链接** —— 私聊机器人直接扔 `https://github.com/owner/repo`。
   会自动探测有没有 `.ipa`、读真实包名和最低系统版本、抓图标、生成配置并提交，约 1 分钟生效。
2. **本地跑脚本** —— `python tools/add_app.py owner/repo`
3. **手写配置** —— 照 `apps/Breeze/config.toml` 抄，改 `[github] repo`、`bundle_identifier`、
   `[versions] asset_pattern` 三个字段就行。

## 自动化

`.github/workflows/` 下两个工作流：

- **`update-sources.yml`** —— 每 6 小时检查所有 app 有无新版本，有就重新生成源并提交
- **`add-app.yml`** —— 收到机器人发来的链接时，自动完成上面「怎么加新 app」的全部步骤

## 致谢

- [bebound/AltGallery](https://github.com/bebound/AltGallery) —— 整个项目框架、生成流程、图标与公告图渲染器
- [bebound/AltGen](https://github.com/bebound/AltGen) —— 实际的源生成工具
- 所有被收录 app 的开源作者

## 许可证

[MIT](LICENSE)，与原项目一致。原版权声明 `Copyright (c) 2026 Hang` 完整保留。

本仓库的修改部分（精简 app 列表、`tools/add_app.py`、`add-app.yml`、README 重写）同样以 MIT 发布。
