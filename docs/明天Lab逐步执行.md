# 明天实验室：可逐项打勾的 30 步清单

## I. 到实验室、装配与安全
1. [ ] 带 STM32 Nucleo-F411RE、ST-LINK USB、M5Stack Weight-I2C HX711、MCP9808、1 kg load cell、100×100×20 mm 亚克力挡板、STL mounter、支架/螺丝、面包板、杜邦线、笔记本。
2. [ ] 保存旧稳定的 5 Hz 固件备份；带本新项目 zip，Arduino IDE 可用，VS Code + Python 能运行。
3. [ ] 断电检查 I2C 连接：PB9 SDA、PB8 SCL、公共 GND，Weight-I2C 通常 5V，MCP9808 3V3；确认 SDA/SCL 电平兼容及上拉，未知则用 3.3V/5V 双向电平转换。
4. [ ] 用手检查板+ mounter+ Load Cell 连接可靠，无松动、无碰撞风箱内壁、无锐边，低风量逐渐升高；30cm envelope 用户已确认合格。
5. [ ] 固定到提供的风洞 mounting plate，挡板正面垂直朝向风，不让支架承受无意外载荷或在风下触碰其它物体。
6. [ ] 问 TA：本组 HX711+1kg Load Cell 是否可用；Arduino IDE 是否确实允许作为提交源码（老师已口头说明）；老师评分脚本对 ASCII/newline or binary float 格式的精确要求。
7. [ ] 问 TA：200Hz Dwyer/Pitot Ground Truth 怎么导出、同步起点如何记录；确认仪器全范围压强-风速曲线，不要仅凭 60Pa=10m/s 一点假设。

## II. 开始前测试（建议在未吹风时）
8. [ ] 若未在宿舍实测，上传 `firmware_Arduino/COMP0219_Stage1/COMP0219_Stage1.ino` + `calibration_config.h`，确保 `COMP0219_AUTOSTART 0`、板型选择 Nucleo-F411RE。
9. [ ] 关闭 Arduino Serial Monitor，核对 USB COM（之前是 COM7，但重插可能变化）：`python -m serial.tools.list_ports -v`。
10. [ ] 运行 `python python/check_200hz.py --port COM7 --seconds 12 --output data/preflight.csv`。查看 200 rows/s 和 missing=0；打印截图并保留 `STREAM_EXIT` 的 missed_slots。若不达标，先排查流输出，不要带着失败去正式演示。
11. [ ] 在普通调试模式运行 logger：`python python/logger_200hz.py --port COM7 --output data/lab_run01.csv`。
12. [ ] 确保 0 Pa、板子静止，输入 `z`，记下 `ZERO,ADC`、`SIGMA`、`TEMP_C`；该命令会清空此前校准。
13. [ ] 看 5–10 秒 `LIVE` 原始数据，确认温度有效、无 ADC timeout；在零附近浮动，没有大幅漂移。

## III. 标定与验证（参考输入只是暂定关系）
14. [ ] 将风箱设为稳定的 3 Pa，等稳定后在 logger 输入 `p 3`，等待 `POINT` 和捕获结束；logger 按暂定公式转发约 `p 2.23607` (m/s)。
15. [ ] 分别设 5、10、22、38、60 Pa，每次等稳定后输入 `p 5`、`p 10`、`p 22`、`p 38`、`p 60`，每档捕获约 5 秒。每档存 `MEAN_ADC`、`STD_ADC`、`REF_MPS`、`TEMP_C`；不要重复执行 `z`。
16. [ ] 至少 2 点后应出现 `MODEL READY`；更推荐全部 6 点后再评价误差，观察最大风速有无饱和、风向响应符号是否稳定。
17. [ ] 做独立验证，按 8/15/30/49 Pa 设置，稳定后输入 `v 8`、`v 15`、`v 30`、`v 49`，不将验证点混进拟合。
18. [ ] 输入 `r`，记录 training MSE、validation MSE / RMSE / Bias；输入 `d` 导出全部 POINT CSV；logger 应生成 `data/lab_run01_calibration_restore.txt`。
19. [ ] 如果模型表现差，先检查机械接触、零漂、原始 ADC 随速度是否单调变化；必要时重新完整标定，新 `z` 会清空旧数据，所以先保存 `r/d`。
20. [ ] 在几个已经校准过的压强重新测试，检查复测重复性与从高到低时的滞后。

## IV. 动态测试与官方 200Hz 参考
21. [ ] 先确认 `j` 200Hz 诊断输出没有丢序号；输入 `x` 停止。`g` 为每行纯数字正式流，不能同时混入 `LIVE` 调试文本。
22. [ ] 保持同一 logger，输入 `phase step` 再 `g`；先稳定在 3 Pa 后用旋钮迅速调整到 22 Pa，并尽量即时输入 `pressure 22`；保持 10–15 秒。记事件时刻、设备噪声；如有官方 200 Hz 参考流应同步记录。
23. [ ] 在 22 Pa 运行稳定后，切回 3 Pa，输入 `pressure 3` 标记；保留整个过程。手动输入事件时间**不能**直接当作真实气流切换时刻。
24. [ ] 输入 `phase ramp`，逐步升高 3→10→22→38→60 Pa，再降回 38→22→10→3 Pa；每变化一次输入 `pressure <Pa>`，连续保留 g 模式 200Hz 输出。
25. [ ] 根据 TA 的方法同步获取 Dwyer/Pitot 200Hz Ground Truth。若无法取得，仍保存手动标注，但报告中仅用于示意曲线，不能声称精确 rise time/lag 或 official MSE。
26. [ ] 输入 `x` 退出 200Hz 流，保留 `STREAM_EXIT` 里 missed_slots、adc_poll_success、adc_value_changes、adc_read_errors、max_late_us。

## V. 结束、备份与论文素材
27. [ ] 风箱关停、装置静止，输入 `q` 检查零点漂移，**不要**轻易执行会清空模型的 `z`。
28. [ ] 输入 `r`、`d`，再次确认 `_calibration_restore.txt` 已保存；然后 `stop` 关闭 logger，不要直接拔线丢文件。
29. [ ] 记录安装正侧照片、STL 结构和实际尺寸、校准流程、滤波参数、采样/输出频率、线材连接、老师 Ground Truth 的来源与精度参数。
30. [ ] 回宿舍运行 `python python/analyze.py --input data/lab_run01.csv --out outputs/lab_run01` 与 `python python/plot_stream_200hz.py --input data/lab_run01.csv --out outputs/stream_lab`。用真实数据替换示例图，整理 code/log/calibration、分析 PDF 进入 supplementary ZIP。

## 正式打分前上电自动输出（在已验证实测参数后）

`python python/make_embedded_config.py --model-file data/lab_run01_calibration_restore.txt`

重新 Arduino 编译上传，`COMP0219_AUTOSTART 1`。此模式上电无需命令即向串口发 200Hz 纯浮点风速，PC 不执行风速估计。注意启动延时和官方测试脚本格式要与 TA 核对；装配有变化要重新标定。**自动启动版不适用于重新运行 z/p 标定；标定前把 AUTOSTART 改回 0。**
