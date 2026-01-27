# GridSage: Carbon-Aware Workload Orchestration System

**GridSage** is a carbon-aware workload orchestration system that leverages Multi-Agent Reinforcement Learning (MARL) to optimize data center operations. By intelligently routing and scheduling workloads based on real-time thermal conditions and carbon intensity data, GridSage reduces the environmental impact of cloud computing.

## Project Overview

Data centers consume approximately 1-2% of global electricity, a figure projected to rise with the proliferation of AI workloads. Traditional Kubernetes schedulers use static rules that ignore the real-time carbon cost of electricity.

GridSage addresses this by treating carbon efficiency as a primary optimization objective. The system employs cooperative MARL agents (MAPPO) that jointly optimize:

1. **Cooling Decisions (Agent A):** Adjusting HVAC intensity based on thermal state.

2. **Migration Decisions (Agent B):** Moving workloads to greener regions only when the long-term carbon savings outweigh the "Migration Tax" (network transfer and cold-start costs).


### Key Goals

* **Reduce Total Environmental Impact (TEI):** Achieve a 38-41% reduction in a composite metric of energy, carbon, and cost compared to naive scheduling.

* **Smart Migration:** Eliminate wasteful "thrashing" by accounting for migration overhead and enforcing a 60-minute hysteresis cooldown buffer.

* **Operational Stability:** Maintain SLA compliance (latency <50ms) and thermal safety (<85°C) at all times.


## Technical Architecture

GridSage operates as a closed-loop control system integrating the following components:

* **Data Ingestion:** Kafka streams for real-time carbon intensity (WattTime API) and thermal sensor data (Kaggle dataset replay).

* **Feature Store:** Feast manages online/offline features for RL inference.

* **MARL Engine:** RLlib MAPPO implementation with a centralized critic and shared reward signal.

* **Orchestration:** A GKE cluster with node pools simulating distinct geographic regions (us-east1 vs. europe-west1).

* **Monitoring:** Prometheus, Grafana, and Evidently AI for drift detection and performance tracking.



## Installation & Setup

### Prerequisites

* Python 3.8+
* Docker & Kubernetes (GKE or Minikube)
* Google Cloud Platform account (for WattTime/GCS integration)

### Installation Steps

1. **Clone the Repository:**
```bash
git clone https://github.com/your-org/GridSage.git
cd GridSage
```

2. **Install Dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure Environment Variables:**
Create a `.env` file with your API keys:
```bash
WATTTIME_USER=<your_username>
WATTTIME_PASS=<your_password>
OPENWEATHER_KEY=<your_key>
```

4. **Deploy Infrastructure (Terraform):**
```bash
cd infra
terraform init
terraform apply
```


## Usage

### Running the Simulation

To start the training loop with simulated data:

```bash
python src/train_mappo.py --episodes 20000 --regions us-east1 europe-west1
```

### Launching the Dashboard

To view the live demo dashboard comparing GridSage against a naive scheduler:

```bash
streamlit run src/dashboard/app.py
```

### Monitoring

Access the Grafana dashboards at `localhost:3000` (default credentials: admin/admin) to view real-time TEI reduction and agent decision logs.

## License

This project is part of the MLOps Capstone (DADS 7305) at Northeastern University.
