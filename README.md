<div align="center">
  <h1>Deep Insight</h1>

  <h2>Production-ready multi-agent framework for building scalable data analysis workflows without infrastructure headaches</h2>

  <div align="center">
    <a href="https://github.com/aws-samples/aws-ai-ml-workshop-kr/graphs/commit-activity"><img alt="GitHub commit activity" src="https://img.shields.io/github/commit-activity/m/aws-samples/aws-ai-ml-workshop-kr"/></a>
    <a href="https://github.com/aws-samples/aws-ai-ml-workshop-kr/blob/master/LICENSE"><img alt="License" src="https://img.shields.io/badge/LICENSE-MIT-green"/></a>
    <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.12+-blue.svg"/></a>
  </div>

  <p>
    <a href="#why-deep-insight">Why Deep Insight?</a>
    ◆ <a href="#quick-start">Quick Start</a>
    ◆ <a href="#demo">Demo</a>
    ◆ <a href="#deployment-options">Deployment Options</a>
  </p>
</div>

## *Latest News* 🔥

- **[2025/12]** File-based code execution - significantly reduces NameError/ImportError rates compared to REPL-based approaches
- **[2025/12]** Output token optimization with shared utils scripts - repeatedly used functions are generated once and imported, reducing redundant code generation
- **[2025/11]** Added per-agent token tracking with detailed metrics - monitor input/output tokens and cache reads/writes for complete cost visibility and optimization
- **[2025/11]** Added editable DOCX report generation - all analysis results are exportable to fully editable Word documents for easy customization and sharing
- **[2025/10]** Released Deep Insight Workshop ([Korean](https://catalog.us-east-1.prod.workshops.aws/workshops/ee17ba6e-edc4-4921-aaf6-ca472841c49b/ko-KR) | [English](https://catalog.us-east-1.prod.workshops.aws/workshops/ee17ba6e-edc4-4921-aaf6-ca472841c49b/en-US))
- **[2025/10]** Added support for Claude Sonnet 4.5 with extended thinking and enhanced reasoning capabilities
- **[2025/09]** Released Deep Insight framework built on Strands SDK and Amazon Bedrock with hierarchical multi-agent architecture

## Are You Facing These Challenges?

### 에이전트 설계, 어디서부터 시작해야 할지 고민이신가요? (Struggling with Agent Architecture?)

Deep Insight provides a **proven hierarchical architecture** with Coordinator, Planner, Supervisor, and specialized tool agents. Start with a working production-grade system and customize from there—no need to design from scratch.

### 프로덕션급 성능의 에이전트, 어떻게 만들어야 할지 막막하신가요? (Need Production-Grade Performance?)

Get **production-grade multi-agent workflows** out of the box with prompt caching, streaming responses, token tracking, and battle-tested performance patterns. Deploy with confidence using architecture validated in real-world scenarios.

### 민감한 데이터를 안전하게 처리하고 싶으신가요? (Concerned About Data Security?)

Deploy Deep Insight in **your own AWS VPC** for complete data isolation and control. All data processing happens within your secure VPC environment, with Amazon Bedrock API calls staying in AWS infrastructure—never exposed to the public internet.

## Why Deep Insight?

Transform weeks of manual reporting work into minutes using hierarchical multi-agent systems built on Strands SDK and Amazon Bedrock.

- **🎨 Full Customization & Control** - Modify agents, prompts, and workflows with complete code access in your AWS VPC
- **🔒 Enterprise-Grade Security** - Single-tenant VPC deployment with complete data isolation
- **🤖 Advanced Multi-Agent Architecture** - Hierarchical workflow with Coordinator, Planner, Supervisor, and specialized tool agents
- **🧠 Flexible Model Selection** - Choose different Claude models for each agent (Sonnet 4, Haiku 4, etc.) via simple .env configuration
- **📊 Transparency & Verifiability** - Reports with calculation methods, sources, and reasoning processes
- **🚀 Beyond Reporting** - Extend to any agent use case: shopping, support, log analysis, and more

## Quick Start

Deep Insight provides two deployment options to match your needs.

### Self-Hosted Deployment

Run agents locally or in your VPC with full control:
- ✅ Complete code access to agents, prompts, and workflows
- ✅ Rapid iteration during development (no rebuild required)
- ✅ Simple setup in ~10 minutes

**Get Started**: [`./self-hosted/`](./self-hosted/) | 📖 [Self-Hosted README](./self-hosted/README.md)

### Managed AgentCore Deployment

Production deployment using AWS Bedrock AgentCore Runtime with VPC Private Mode:
- ✅ AWS-managed infrastructure with CloudFormation
- ✅ 100% private network (VPC endpoints, no public internet)
- ✅ Dynamic Fargate containers for code execution

**Get Started**: [`./managed-agentcore/`](./managed-agentcore/) | 📖 [Managed AgentCore README](./managed-agentcore/README.md)

## Deployment Options

| Feature | Self-Hosted | Managed AgentCore |
|---------|-------------|-------------------|
| Setup Time | ~10 minutes | ~45 minutes |
| Infrastructure | Local/EC2 | AWS Fargate + VPC |
| Network | Your choice | 100% Private VPC |
| Best For | Development, Testing | Production, Enterprise |

---

## Demo

### Fresh Food Sales Data Analysis

> **Task**: "Create a sales performance report for Moon Market. Analyze from sales and marketing perspectives, generate charts and extract insights, then create a docx file. The analysis target is the `./data/Dat-fresh-food-claude.csv` file."
>
> **Workflow**: Input (CSV data file: `Dat-fresh-food-claude.csv`) → Process (Natural language prompt: "Analyze sales performance, generate charts, extract insights") → Output (DOCX report with analysis, visualizations, and marketing insights)

[▶️ Watch Full Demo on YouTube](https://www.youtube.com/watch?v=pn5aPfYSnp0)

### Sample Outputs

📄 [English Report](./self-hosted/assets/report_en.docx) | 📄 [Korean Report](./self-hosted/assets/report.docx)

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

### Quick Start for Contributors

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/aws-samples/sample-deep-insight.git
cd sample-deep-insight

# Follow the self-hosted setup instructions
cd self-hosted
cd setup/ && ./create-uv-env.sh deep-insight 3.12 && cd ..

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes, test, then commit and push
git add .
git commit -m "Add feature: description"
git push origin feature/your-feature-name

# Open a Pull Request on GitHub
```

### Contribution Areas

- **New Agent Types**: Add specialized agents for specific domains
- **Tool Integration**: Create new tools for agent capabilities
- **Model Support**: Add support for additional LLM providers
- **Documentation**: Improve guides, examples, and tutorials
- **Bug Fixes**: Fix issues and improve stability
- **Performance**: Optimize streaming, caching, and execution

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

### Philosophy

> **"Come From Open Source, Back to Open Source"**

We believe in the power of open collaboration. Deep Insight takes the excellent work of the LangManus community and extends it with AWS-native capabilities, then contributes those enhancements back to the community.

## Contributors

| Name | Role | Contact |
|------|------|---------|
| **Dongjin Jang, Ph.D.** | AWS Sr. AI/ML Specialist SA | [Email](mailto:dongjinj@amazon.com) · [LinkedIn](https://www.linkedin.com/in/dongjin-jang-kr/) · [GitHub](https://github.com/dongjin-ml) · [Hugging Face](https://huggingface.co/Dongjin-kr) |
| **Gonsoo Moon** | AWS Sr. AI/ML Specialist SA | [Email](mailto:moongons@amazon.com) · [LinkedIn](https://www.linkedin.com/in/gonsoomoon) · [GitHub](https://github.com/gonsoomoon-ml) · [Hugging Face](https://huggingface.co/Gonsoo) |
| **Chloe(Younghwa) Kwak** | AWS Sr. Solutions Architect | [Email](mailto:younghwa@amazon.com) · [LinkedIn](https://www.linkedin.com/in/younghwakwak) · [GitHub](https://github.com/chloe-kwak) · [Hugging Face](https://huggingface.co/Chloe-yh) |
| **Yoonseo Kim** | AWS Solutions Architect | [Email](mailto:ottlseo@amazon.com) · [LinkedIn](https://www.linkedin.com/in/ottlseo/) · [GitHub](https://github.com/ottlseo) |
| **Jiyun Park** | AWS Solutions Architect | [Email](mailto:jiyunp@amazon.com) · [LinkedIn](https://www.linkedin.com/in/jiyunpark1128/) · [GitHub](https://github.com/glossyyoon) |

---

<div align="center">
  <p>
    <strong>Built with ❤️ by AWS KOREA SA Team</strong><br>
    <sub>Empowering enterprises to build customizable agentic AI systems</sub>
  </p>
</div>
