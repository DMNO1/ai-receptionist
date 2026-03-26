# Railway 部署方案

## 快速部署步骤

### 1. 准备代码
```bash
git clone https://github.com/DMNO1/ai-receptionist.git
cd ai-receptionist
```

### 2. 部署到Railway
```bash
# 安装Railway CLI
npm install -g @railway/cli

# 登录
railway login

# 初始化项目
railway init

# 部署
railway up
```

### 3. 配置环境变量
在Railway Dashboard中设置以下变量：
- `DATABASE_URL` - Railway会自动提供PostgreSQL
- `DEEPSEEK_API_KEY` - DeepSeek API密钥
- `WECOM_TOKEN` - 企业微信Token（可选）
- `WECOM_CORP_ID` - 企业微信CorpID（可选）
- `WECOM_SECRET` - 企业微信Secret（可选）

### 4. 自定义域名（可选）
在Railway Dashboard中添加自定义域名。

## 成本估算
- Railway: $5/月（含PostgreSQL）
- 阿里云ECS: ¥50-100/月
- 腾讯云轻量: ¥50/月

## 推荐方案
1. **MVP测试**: Railway ($5/月)
2. **正式生产**: 阿里云ECS + RDS (¥200-300/月)
3. **低成本**: 腾讯云轻量应用服务器 (¥50/月)
