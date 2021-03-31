use serde::{Deserialize, Serialize};

use crate::common::Map;
use crate::{TaskId, WorkerId, TaskTypeId};
use crate::PriorityValue;
use crate::messages::common::{TaskFailInfo, SubworkerDefinition};

#[derive(Serialize, Deserialize, Debug)]
pub struct WorkerRegistrationResponse {
    pub worker_id: WorkerId,
    pub worker_addresses: Map<WorkerId, String>,
    pub subworker_definitions: Vec<SubworkerDefinition>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ComputeTaskMsg {
    pub id: TaskId,

    pub type_id: TaskTypeId,

    #[serde(skip_serializing_if = "Vec::is_empty")]
    #[serde(default)]
    pub dep_info: Vec<(TaskId, u64, Vec<WorkerId>)>,

    #[serde(with = "serde_bytes")]
    pub spec: Vec<u8>,

    pub user_priority: PriorityValue,
    pub scheduler_priority: PriorityValue,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct TaskIdsMsg {
    pub ids: Vec<TaskId>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct NewWorkerMsg {
    pub worker_id: WorkerId,
    pub address: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct TaskIdMsg {
    pub id: TaskId,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "op")]
pub enum ToWorkerMessage {
    ComputeTask(ComputeTaskMsg),
    DeleteData(TaskIdMsg),
    StealTasks(TaskIdsMsg),
    NewWorker(NewWorkerMsg),
    RegisterSubworker(SubworkerDefinition),
}

#[derive(Deserialize, Serialize, Debug)]
pub struct TaskFinishedMsg {
    pub id: TaskId,
    pub size: u64,
    /*#[serde(with = "serde_bytes")]
    pub r#type: Vec<u8>,*/
}

#[derive(Deserialize, Serialize, Debug)]
pub struct TaskFailedMsg {
    pub id: TaskId,
    pub info: TaskFailInfo,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct DataDownloadedMsg {
    pub id: TaskId,
}

#[derive(Deserialize, Serialize, Debug)]
pub enum StealResponse {
    Ok,
    NotHere,
    Running,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct StealResponseMsg {
    pub responses: Vec<(TaskId, StealResponse)>,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "op")]
pub enum FromWorkerMessage {
    TaskFinished(TaskFinishedMsg),
    TaskFailed(TaskFailedMsg),
    DataDownloaded(DataDownloadedMsg),
    StealResponse(StealResponseMsg),
}