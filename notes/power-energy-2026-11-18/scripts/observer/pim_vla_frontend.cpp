#include "ramulator/controller/impl/pim_model.h"
#include "ramulator/frontend/impl/json_input.h"
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <sstream>

namespace PimVla {
int run_fused_kernels(const std::string& config_file,const std::string& output);
std::string json_string(const std::string& value) {
  std::ostringstream out;out<<'"';
  for(unsigned char c:value) {
    if(c=='"'||c=='\\')out<<'\\'<<c;
    else if(c=='\n')out<<"\\n";
    else if(c=='\r')out<<"\\r";
    else if(c=='\t')out<<"\\t";
    else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;
    else out<<c;
  }
  out<<'"';return out.str();
}
struct Event {std::string kind,name;double us=0;int step=0,layer=0;};
struct StageResult {int id,step,layer;std::string name;Clock start,end,wait=0;};
enum class VlmGpuState { running, draining, paused };

namespace {
ConfigNode load_spec(const ConfigNode& cfg) {
  auto spec=cfg["spec"];
  if(!spec)spec=cfg["spec_path"];
  if(spec.is_scalar())spec=Config::parse_config_file(spec.as<std::string>());
  return spec;
}

int hardware_window(const ConfigNode& cfg) {
  const int w=cfg["w_max"].as<int>(128);
  require(w==128||w==256,"w_max must be 128 or 256");
  return w;
}

void set_watermarks(PIMController& mc,int w_max) {
  mc.write_high=3*w_max/4;
  mc.write_low=w_max/4;
}

Kernel read_kernel(const ConfigNode& x,double alpha,double tick_us) {
  Kernel k;k.ordinal=x["ordinal"].as<int>();k.name=x["name"].as<std::string>();k.kind=x["kind"].as<std::string>();k.us=x["us"].as<double>();
  k.reads=x["read_sectors"].as<uint64_t>();k.proxy=x["write_is_proxy"].as<bool>(true);
  k.writes=x["write_sectors"].as<uint64_t>();if(k.proxy)k.writes=static_cast<uint64_t>(std::ceil(alpha*k.writes));
  k.base=x["base_sector"].as<uint64_t>();require(k.base%16==0,"kernel base must be channel aligned");
  k.read_address_extent_sectors=x["read_address_extent_sectors"].as<uint64_t>(k.reads);
  require(k.read_address_extent_sectors>=k.reads,"read addresses exceed the original region");
  k.nominal=static_cast<Clock>(std::ceil(k.us/tick_us-1e-10));
  return k;
}

Clock isolated_memory(const ConfigNode& spec, const Kernel& k, int w_max) {
  Clock last=0;
  // A fresh controller's schedule is invariant to channel ID for the same
  // request counts. The remainder of the striped reads or writes is the
  // only reason to simulate another channel in an isolated probe.
  std::array<bool,4> seen{};
  for(int c=0;c<16;++c) {
    const int stripe=2*(c<k.reads%16)+(c<k.writes%16);
    if(seen[stripe])continue;
    seen[stripe]=true;
    PIMController mc(c,spec,spec["metadata"]);
    set_watermarks(mc,w_max);
    mc.begin_kernel(&k,0);
    Clock now=0;
    while(!mc.kernel_finished())now=mc.step(now,true);
    last=std::max(last,mc.kernel_memory_done);
  }
  return last;
}

int probe_mlp(const std::string& config_file) {
  const auto cfg=Config::parse_config_file(config_file);
  const auto spec=load_spec(cfg);
  const int w_max=hardware_window(cfg);
  const double tick_us=spec["clock_ps"].as<double>(938.0)/1000000.0;
  const auto vlm=Config::parse_config_file(cfg["vlm_path"].as<std::string>());
  const auto units=vlm["units"];
  std::map<int,Kernel> kernels;
  for(const auto& x:units.seq()) {
    auto k=read_kernel(x,1.0,tick_us);
    require(kernels.emplace(k.ordinal,std::move(k)).second,"duplicate VLM ordinal");
  }
  int ordinal=0,w=0;
  while(std::cin>>ordinal>>w) {
    require(w>=1&&w<=w_max,"probe window outside hardware limits");
    auto k=kernels.at(ordinal);
    k.mlp=w;
    std::cout<<isolated_memory(spec,k,w)<<std::endl;
  }
  require(std::cin.eof(),"invalid probe request");
  return 0;
}
}

int run(const std::string& config_file,const std::string& output) {
  auto cfg=Config::parse_config_file(config_file);
  auto execution=cfg["execution_model"].as<std::string>("native_dram_requests");
  const bool trace=cfg["trace_ae_dq"].as<bool>(false);
  const bool diagnostics=cfg["bus_diagnostics"].as<bool>(false);
  const bool power_stats=cfg["dram_power_stats"].as<bool>(false);
  const int trace_channel=cfg["trace_channel"].as<int>(-1);
  const bool trace_ca=cfg["trace_ca_commands"].as<bool>(true);
  require(trace_channel>=-1&&trace_channel<16,"trace_channel must be -1 or 0..15");
  const auto quantum_cfg=cfg["vlm_gpu_quantum_us"];
  require(!quantum_cfg||execution=="native_dram_requests","vlm_gpu_quantum_us requires native_dram_requests");
  require(!trace||execution=="native_dram_requests","trace_ae_dq requires native_dram_requests");
  require(!power_stats||execution=="native_dram_requests","power stats requires native requests");
  if(execution=="fused_kernel_windows")return run_fused_kernels(config_file,output);
  require(execution=="native_dram_requests","unknown execution_model");
  require(cfg.is_map()&&!cfg.map().count("refresh_allbank"),"refresh_allbank is retired: rank0 uses REFpb and rank1 uses REFab");
  std::filesystem::create_directories(output);
  ConfigNode specification=load_spec(cfg);
  double tick_us=specification["clock_ps"].as<double>(938.0)/1000000.0;
  auto cycles=[&](double us){return static_cast<Clock>(std::ceil(us/tick_us-1e-10));};
  auto us=[&](Clock c){return c*tick_us;};
  std::string kind=cfg["run_kind"].as<std::string>("combined");
  require(kind=="combined"||kind=="ae_solo"||kind=="vlm_solo","invalid run_kind");
  require(!trace||kind!="vlm_solo","trace_ae_dq requires an AE workload");
  std::ofstream bursts,commands,epochs,timeline;
  if(trace) {
    bursts.open(output+"/dq-bursts.csv");
    commands.open(output+"/ca-commands.csv");
    epochs.open(output+"/dq-epochs.csv");
    timeline.open(output+"/dq-timeline.json");
    require(bursts&&commands&&epochs&&timeline,"cannot open AE bus trace files");
    bursts<<"channel,stage_id,stage,start_ck,end_ck,direction,command,fused_io_epoch\n";
    commands<<"channel,stage_id,start_ck,end_ck,command,rank,bank_group,bank,row,column,opcode,bank_mask\n";
    epochs<<"channel,stage_id,start_ck,end_ck\n";
    timeline<<"{\"clock_ps\":"<<std::setprecision(15)<<tick_us*1000000<<",\"channels\":16,\"events\":[";
  }
  bool do_ae=kind!="vlm_solo",do_vlm=kind!="ae_solo";
  bool serial=cfg["mode"].as<std::string>("concurrent")=="serial";
  const double quantum_us=quantum_cfg.as<double>(0);
  require(!quantum_cfg||(kind=="combined"&&!serial&&std::isfinite(quantum_us)&&quantum_us>0&&quantum_us<=5000000),
          "vlm_gpu_quantum_us must be positive and at most 5000000 in a concurrent combined run");
  const Clock vlm_quantum=quantum_cfg?std::max<Clock>(1,cycles(quantum_us)):0;
  require(!power_stats||!serial,"power stats currently requires concurrent or solo epochs");
  bool fused=cfg["dataflow"].as<std::string>("streaming")=="fused";
  std::string policy=cfg["arbitration"].as<std::string>("frfcfs");
  if(policy.empty())policy="frfcfs";
  std::string layout=cfg["layout"].as<std::string>("feature"),rope=cfg["rope"].as<std::string>("gpu");
  require(layout=="feature"||layout=="token","invalid layout");
  const auto model=cfg["model"].as<std::string>("pi05");
  require(model=="pi05"||model=="gr00t_n16","unknown workload model");
  require(model=="pi05" ? rope=="gpu"||rope=="local" : rope=="none","RoPE location differs from workload model");
  require(layout!="feature"||(!fused&&(model!="pi05"||rope=="gpu")),"invalid feature layout dataflow or RoPE");
  bool arbitration_present=bool(cfg["arbitration"])&&!cfg["arbitration"].as<std::string>("").empty();
  require(arbitration_present==(!serial&&!fused),"arbitration is required only for concurrent streaming");
  require(policy=="frfcfs"||policy=="pim_head"||policy=="pim_lookahead"||policy=="gap_batch","invalid arbitration");
  auto calib=cfg["calibration"];
  const auto release=cfg["vlm_release"].as<std::string>("closed_loop");
  require(release=="closed_loop"||release=="uniform","invalid vlm_release");
  const bool closed=release=="closed_loop";
  require(closed ? !calib : (!cfg["w_max"]&&!cfg["mlp_path"]),
          "legacy calibration and closed-loop settings cannot be combined");
  const int w_max=closed?hardware_window(cfg):0;
  double alpha=closed?1.0:calib["alpha"].as<double>(1);
  require(alpha>=0.05&&alpha<=1,"alpha outside registered calibration range [0.05,1]");
  std::array<std::unique_ptr<PIMController>,16> channels;
  for(int c=0;c<16;c++) {
    channels[c]=std::make_unique<PIMController>(c,specification,specification["metadata"]);
    auto& mc=*channels[c];mc.fused=fused;mc.policy=policy;mc.legacy_gap_batch=!closed;
    if(power_stats)mc.power_stats=std::make_unique<DramPowerStats>(mc.device);
    if(trace&&(trace_channel<0||trace_channel==c)) {
      mc.checker.dq_trace=&bursts;
      mc.checker.ca_trace=trace_ca?&commands:nullptr;
      mc.checker.epoch_trace=(fused||diagnostics)?&epochs:nullptr;
      mc.checker.trace_channel=c;
    }
    mc.checker.split_traffic=(closed&&do_ae&&do_vlm)||diagnostics;
    if(closed)set_watermarks(mc,w_max);
    else {
      mc.window=calib["window"].as<int>(64);mc.write_high=calib["write_high"].as<int>(48);mc.write_low=calib["write_low"].as<int>(16);
      require(mc.window>0&&mc.write_low>=0&&mc.write_low<mc.write_high&&mc.write_high<=mc.window,"invalid write watermarks/window");
    }
  }
  std::map<std::string,ProgramStage> programs;
  int layer_stride_rows=512;
  std::vector<Event> events;
  if(do_ae) {
    int layer_stride_bytes=0;
    std::string program_model, workload_model;
    programs=read_program_json(cfg["program_path"].as<std::string>(),&layer_stride_bytes,&program_model,&workload_model);
    require(!closed||program_model!="fused_kernel_windows","closed loop requires a native request program");
    require(layer_stride_bytes>0&&layer_stride_bytes%2048==0,"layer stride must contain complete DRAM rows");
    layer_stride_rows=layer_stride_bytes/2048;
    auto schedule=Config::parse_config_file(cfg["ae_schedule_path"].as<std::string>());
    require(workload_model==model&&schedule["model"].as<std::string>("pi05")==model,
            "AE program and schedule must match the workload model");
    const int layer_capacity=specification["organization"]["row"].as<int>(32768)/layer_stride_rows;
    const int layers=schedule["layers"].as<int>(0);
    require(layers>=0&&layers<=layer_capacity,"AE layers exceed rank1 bank capacity");
    const auto schedule_events=schedule["events"];
    for(const auto& e:schedule_events.seq()) {
      Event v;v.kind=e["kind"].as<std::string>();v.name=e[v.kind=="pim"?"stage":"name"].as<std::string>();
      v.us=e["us"].as<double>(0);v.step=e["step"].as<int>(0);v.layer=e["layer"].as<int>(0);
      require(v.kind=="gpu"||programs.count(v.name),"AE stage has no PIM program: "+v.name);
      require(v.kind=="gpu"||v.layer<layer_capacity,"AE event exceeds rank1 bank capacity");
      events.push_back(v);
    }
  }
  std::vector<Kernel> kernels;
  if(do_vlm) {
    auto input=Config::parse_config_file(cfg["vlm_path"].as<std::string>());
    require(input["model"].as<std::string>("pi05")==model,"VLM workload must match the configured model");
    const auto input_units=input["units"];
    ConfigNode mlp_units;
    if(cfg["mlp_path"]) {
      const auto mlp=Config::parse_config_file(cfg["mlp_path"].as<std::string>());
      require(mlp["kind"].as<std::string>()=="kernel_mlp"&&mlp["w_max"].as<int>()==w_max,
              "MLP ledger model or hardware window differs");
      mlp_units=mlp["units"];
      require(mlp_units.size()==input_units.size(),"MLP ledger must cover all VLM units");
    }
    for(const auto& x:input_units.seq()) {
      Kernel k=read_kernel(x,alpha,tick_us);
      k.mlp=w_max;
      if(mlp_units) {
        const auto& row=mlp_units.seq().at(kernels.size());
        require(row["ordinal"].as<int>()==k.ordinal,"MLP ledger ordinal differs from VLM input");
        k.mlp=row["w_k"].as<int>();
        require(k.mlp>=1&&k.mlp<=w_max,"MLP ledger window outside hardware limits");
      }
      kernels.push_back(k);
    }
  }
  std::vector<StageResult> results;
  Clock now=0,ae_end=0,ae_gpu_end=NEVER,wait_since=-1,wait_total=0;
  bool pim_active=false,ae_gpu_active=false,ae_recorded=!do_ae,serial_epoch_reset=false;
  size_t ae_index=0,vlm_index=0;
  int active_kernel=-1;
  VlmGpuState vlm_gpu_state=VlmGpuState::running;
  Clock vlm_checkpoint=NEVER,vlm_pause_start=0,max_gpu_wait=0;
  uint64_t vlm_yields=0;
  Clock stage_start=0;
  Clock gpu_start=0;
  auto trace_event=[&](Clock start,Clock end,int stage_id) {
    if(!trace)return;
    const auto& e=events[ae_index];
    if(ae_index)timeline<<',';
    timeline<<"\n{\"kind\":"<<json_string(e.kind)<<",\"name\":"<<json_string(e.name)
            <<",\"stage_id\":"<<stage_id<<",\"step\":"<<e.step<<",\"layer\":"<<e.layer
            <<",\"start_ck\":"<<start<<",\"end_ck\":"<<end<<'}';
  };
  std::array<Clock,16> next_tick{};
  uint64_t iterations=0;
  auto all=[&](auto predicate){for(const auto& mc:channels)if(!predicate(*mc))return false;return true;};
  for(;;) {
    bool state_changed=true;
    while(state_changed) {
      state_changed=false;
      const Clock vlm_execution_time=vlm_gpu_state==VlmGpuState::running?now:vlm_pause_start;
      if(active_kernel>=0&&vlm_gpu_state!=VlmGpuState::paused&&
         vlm_execution_time>=kernels[active_kernel].start+kernels[active_kernel].paused+kernels[active_kernel].nominal&&
         all([](const auto& mc){return mc.kernel_finished();})) {
        auto& k=kernels[active_kernel];
        k.end=now;
        for(auto& mc:channels) {
          k.memory_done=std::max(k.memory_done,mc->kernel_memory_done);
          mc->end_kernel();
        }
        if(closed)require(k.end==std::max(k.start+k.paused+k.nominal,k.memory_done),"closed-loop kernel completion was not causal");
        vlm_gpu_state=VlmGpuState::running;vlm_checkpoint=NEVER;
        active_kernel=-1;state_changed=true;
      }
      if(ae_gpu_active&&now>=ae_gpu_end) {
        trace_event(gpu_start,ae_gpu_end,-1);
        ae_gpu_active=false;ae_gpu_end=NEVER;++ae_index;state_changed=true;
      }
      if(pim_active&&all([&](const auto& mc){return mc.stage_finished(now);})) {
        const auto& e=events[ae_index];
        trace_event(stage_start,now,static_cast<int>(results.size()));
        results.push_back({static_cast<int>(results.size()),e.step,e.layer,e.name,stage_start,now,0});
        pim_active=false;++ae_index;for(auto& mc:channels){mc->checker.set_stage(now,-1);if(mc->power_stats)mc->power_stats->set_stage(now,-1);mc->stage=-1;}state_changed=true;
      }
      if(!ae_gpu_active&&!pim_active&&ae_index<events.size()) {
        const auto& e=events[ae_index];
        if(e.kind=="gpu") {
          if(active_kernel<0||vlm_gpu_state==VlmGpuState::paused) {
            if(wait_since>=0) {
              Clock wait=now-wait_since;wait_total+=wait;
              max_gpu_wait=std::max(max_gpu_wait,wait);
              if(!results.empty())results.back().wait+=wait;
              wait_since=-1;
            }
            ae_gpu_active=true;ae_gpu_end=now+cycles(e.us);state_changed=true;
            if(trace)gpu_start=now;
          } else if(wait_since<0)wait_since=now;
        } else {
          stage_start=now;pim_active=true;
          if(trace)for(auto& mc:channels)mc->checker.trace_stage_name=&e.name;
          for(int c=0;c<16;c++){channels[c]->row_offset=std::max(0,e.layer)*layer_stride_rows;channels[c]->set_stage(programs.at(e.name).channels[c],results.size(),now,e.name);next_tick[c]=now;}
          state_changed=true;
        }
      }
      if(ae_index==events.size()&&!pim_active&&!ae_gpu_active&&!ae_recorded) {ae_end=now;ae_recorded=true;state_changed=true;}
      bool pending_ae_gpu=ae_index<events.size()&&!pim_active&&events[ae_index].kind=="gpu";
      if(!ae_recorded&&now>=vlm_checkpoint) {
        vlm_checkpoint=now+vlm_quantum;
        if(pending_ae_gpu) {
          // Yield at a checkpoint only when AE needs the GPU. Let accepted
          // requests complete before switching owners and preserve the cursor.
          vlm_gpu_state=VlmGpuState::draining;
          vlm_pause_start=now;vlm_checkpoint=NEVER;
          next_tick.fill(now);
        }
      }
      if(vlm_gpu_state==VlmGpuState::draining&&all([](const auto& mc){return mc.gpu_outstanding==0;})) {
        vlm_gpu_state=VlmGpuState::paused;
        ++vlm_yields;
        state_changed=true;
      }
      if(vlm_gpu_state==VlmGpuState::paused&&!ae_gpu_active&&!pending_ae_gpu) {
        kernels[active_kernel].paused+=now-vlm_pause_start;
        vlm_gpu_state=VlmGpuState::running;
        vlm_checkpoint=ae_recorded?NEVER:now+vlm_quantum;
        next_tick.fill(now);
        state_changed=true;
      }
      if(active_kernel<0&&vlm_index<kernels.size()&&!ae_gpu_active&&!pending_ae_gpu&&(!serial||ae_recorded)) {
        if(serial&&do_ae&&do_vlm&&!serial_epoch_reset) {
          for(auto& mc:channels)mc->reset_serial_epoch(now);
          serial_epoch_reset=true;
        }
        active_kernel=vlm_index++;kernels[active_kernel].start=now;
        if(vlm_quantum&&!ae_recorded)vlm_checkpoint=now+vlm_quantum;
        for(int c=0;c<16;c++){channels[c]->begin_kernel(&kernels[active_kernel],now);next_tick[c]=now;}
        state_changed=true;
      }
    }
    if(ae_recorded&&active_kernel<0&&vlm_index==kernels.size())break;
    // Only controllers whose event is due run. Their next event is obtained
    // from native ready clocks, completion queues and release timestamps.
    const bool permit_gpu=active_kernel>=0&&vlm_gpu_state!=VlmGpuState::paused;
    const bool release_gpu=vlm_gpu_state==VlmGpuState::running;
    for(int c=0;c<16;c++)if(next_tick[c]<=now)next_tick[c]=channels[c]->step(now,permit_gpu,release_gpu);
    Clock next=*std::min_element(next_tick.begin(),next_tick.end());
    next=std::min(next,ae_gpu_end);
    if(active_kernel>=0&&release_gpu) {
      Clock nominal=kernels[active_kernel].start+kernels[active_kernel].paused+kernels[active_kernel].nominal;
      if(nominal>now)next=std::min(next,nominal);
      if(!ae_recorded)next=std::min(next,vlm_checkpoint);
    }
    require(next>=now&&next<NEVER,"frontend event deadlock");
    if(++iterations%10000000==0)std::cerr<<"progress ck="<<now<<" kernels="<<vlm_index<<" stages="<<results.size()<<"\n";
    now=next;
    require(now<cycles(5000000),"simulation exceeded 5 seconds of model time");
  }
  if(trace) {
    timeline<<"\n],\"ae_end_ck\":"<<ae_end<<"}\n";
    bursts.close();commands.close();epochs.close();timeline.close();
    require(bursts&&commands&&epochs&&timeline,"failed to write AE bus trace files");
  }
  uint64_t gr=0,gw=0,pr=0,pw=0,checks=0;
  for(const auto& mc:channels){mc->checker.advance(now);gr+=mc->gpu_read_bytes;gw+=mc->gpu_write_bytes;pr+=mc->pim_read_bytes;pw+=mc->pim_write_bytes;checks+=mc->checker.checked;}
  std::ofstream out(output+"/raw.json");out<<std::setprecision(15);
  out<<"{\n\"schema_version\":1,\"clock_ps\":"<<tick_us*1000000;
  if(closed)out<<",\"execution_model\":\"native_dram_requests\",\"vlm_release\":\"closed_loop\",\"w_max\":"<<w_max;
  out<<",\"refresh_policy\":{\"rank0\":\"REFpb\",\"rank1\":\"REFab\"},\"refresh_commands\":{";
  for(int rank=0;rank<2;++rank) {
    uint64_t pb=0,ab=0;for(const auto& mc:channels){pb+=mc->refresh_counts[rank][0];ab+=mc->refresh_counts[rank][1];}
    if(rank)out<<',';
    out<<"\"rank"<<rank<<"\":{\"REFpb\":"<<pb<<",\"REFab\":"<<ab<<'}';
  }
  out<<"},\"metrics\":{";
  out<<"\"AE_elapsed_us\":"<<us(ae_end)<<",\"AE_GPU_wait_us\":"<<us(wait_total)<<",\"VLM_remaining_us\":"<<us(do_ae?now-ae_end:now)<<",\"total_us\":"<<us(now);
  out<<",\"gpu_read_bytes\":"<<gr<<",\"gpu_write_bytes\":"<<gw<<",\"pim_read_bytes\":"<<pr<<",\"pim_write_bytes\":"<<pw<<",\"checked_commands\":"<<checks<<",\"serial_epoch_reset\":"<<(serial_epoch_reset?"true":"false");
  if(vlm_quantum)out<<",\"VLM_GPU_yields\":"<<vlm_yields<<",\"AE_GPU_wait_max_us\":"<<us(max_gpu_wait);
  for(const auto& pair:std::vector<std::pair<std::string,std::string>>{{"ACT1","GPU_act1"},{"ACT2","GPU_act2"},{"PREpb","GPU_prepb"},{"PREab","GPU_preab"},{"RD","GPU_reads"},{"WR","GPU_writes"}}) {
    uint64_t count=0;for(const auto& mc:channels)count+=mc->gpu_command_counts[mc->device.m_spec->get_command_id(pair.first)];
    out<<",\""<<pair.second<<"\":"<<count;
  }
  uint64_t hits=0,misses=0;for(const auto& mc:channels){hits+=mc->gpu_row_hits;misses+=mc->gpu_row_misses;}
  uint64_t reordered=0,prefetched=0;for(const auto& mc:channels){reordered+=mc->out_of_order_issues;prefetched+=mc->prefetched_prerequisites;}
  out<<",\"GPU_row_hits\":"<<hits<<",\"GPU_row_misses\":"<<misses
     <<",\"PIM_out_of_order_issues\":"<<reordered<<",\"PIM_prefetched_prerequisites\":"<<prefetched<<"},\n\"stages\":[";
  for(size_t i=0;i<results.size();i++){const auto& r=results[i];if(i)out<<',';
    out<<"{\"stage_id\":"<<r.id<<",\"name\":"<<json_string(r.name)<<",\"step\":"<<r.step<<",\"layer\":"<<r.layer<<",\"start_us\":"<<us(r.start)<<",\"end_us\":"<<us(r.end)<<",\"duration_us\":"<<us(r.end-r.start)<<",\"gpu_wait_us\":"<<us(r.wait)<<"}";}
  out<<"],\n\"kernels\":[";
  for(size_t i=0;i<kernels.size();i++){const auto& k=kernels[i];if(i)out<<',';
    out<<"{\"ordinal\":"<<k.ordinal<<",\"start_us\":"<<us(k.start)<<",\"end_us\":"<<us(k.end)<<",\"duration_us\":"<<us(k.end-k.start)<<",\"read_bytes\":"<<k.reads*32<<",\"write_bytes\":"<<k.writes*32;
    if(vlm_quantum)out<<",\"paused_us\":"<<us(k.paused);
    if(closed)out<<",\"w_k\":"<<k.mlp<<",\"floor_ck\":"<<k.nominal<<",\"memory_ck\":"<<k.memory_done-k.start;
    out<<"}";}
  Clock background_duration=now;
  for(const auto& r:results)background_duration-=r.end-r.start;
  out<<"],\n\"bus\":[";bool comma=false;
  for(int c=0;c<16;c++)for(const auto& [sid,s]:channels[c]->checker.stats){if(comma)out<<',';comma=true;
    Clock duration=sid<0?background_duration:results.at(sid).end-results.at(sid).start;
    out<<"{\"channel\":"<<c<<",\"stage_id\":"<<sid<<",\"ca_cycles\":"<<s.ca<<",\"dq_cycles\":"<<s.dq<<",\"read_bytes\":"<<s.read<<",\"write_bytes\":"<<s.write<<",\"gpu_read_bytes\":"<<s.gpu_read<<",\"gpu_write_bytes\":"<<s.gpu_write<<",\"pim_read_bytes\":"<<s.pim_read<<",\"pim_write_bytes\":"<<s.pim_write<<",\"duration_cycles\":"<<duration;
    if(sid>=0&&closed&&do_ae&&do_vlm) {
      out<<",\"phase_cycles\":{";
      auto phase=[&](const char* name,const BusUtilization& u) {
        out<<json_string(name)<<":{\"duration\":"<<u.duration<<",\"gpu_ca\":"<<u.ca[0]
           <<",\"pim_ca\":"<<u.ca[1]<<",\"pim_private_ca\":"<<u.private_ca
           <<",\"gpu_dq\":"<<u.dq[0]<<",\"pim_dq\":"<<u.dq[1]<<"}";
      };
      phase(fused?"private":"streaming",s.phases[0]);
      if(fused) {out<<',';phase("io_epoch",s.phases[1]);}
      out<<'}';
    }
    out<<"}";}
  out<<"]\n}\n";out.close();
  if(diagnostics) {
    std::ofstream diag(output+"/bus-diagnostics.json");
    diag<<"{\"schema_version\":1,\"trace_channel\":"<<trace_channel
        <<",\"rank0\":\"GPU\",\"rank1\":\"PIM\",\"stages\":[";
    bool sep=false;
    for(int c=0;c<16;++c)for(const auto& [sid,s]:channels[c]->checker.stats) {
      if(sid<0)continue;
      if(sep)diag<<',';
      sep=true;
      const auto& a=s.phases[0];const auto& b=s.phases[1];
      diag<<"{\"channel\":"<<c<<",\"stage_id\":"<<sid
          <<",\"duration_ck\":"<<a.duration+b.duration
          <<",\"gpu_ca_ck\":"<<a.ca[0]+b.ca[0]
          <<",\"pim_ca_ck\":"<<a.ca[1]+b.ca[1]
          <<",\"gpu_dq_ck\":"<<a.dq[0]+b.dq[0]
          <<",\"pim_dq_ck\":"<<a.dq[1]+b.dq[1]
          <<",\"io_epoch_ck\":"<<b.duration
          <<",\"io_epoch_gpu_dq_ck\":"<<b.dq[0]<<'}';
    }
    diag<<"]}\n";diag.close();require(bool(diag),"failed to write bus diagnostics");
  }
  if(power_stats) {
    std::ofstream power(output+"/dram-power-stats.json");
    power<<"{\"schema_version\":1,\"clock_ps\":"<<std::setprecision(15)<<tick_us*1000000
         <<",\"elapsed_ck\":"<<now<<",\"state_names\":[\"precharged\",\"activating\",\"active\",\"precharging\",\"refreshing\"],\"command_names\":[";
    const auto& names=channels[0]->device.m_spec->command_names;
    for(size_t i=0;i<names.size();++i){if(i)power<<',';power<<json_string(names[i]);}
    power<<"],\"channels\":[";
    for(int c=0;c<16;++c){if(c)power<<',';channels[c]->power_stats->finish(now);channels[c]->power_stats->write(power,c);}
    power<<"]}\n";power.close();require(bool(power),"failed to write DRAM power statistics");
  }
  std::cout<<"completed "<<kind<<" total_us="<<us(now)<<" commands="<<checks<<"\n";
  return 0;
}
}
int main(int argc,char** argv) {
  try {
    if(argc==3&&std::string(argv[1])=="--probe-mlp")return PimVla::probe_mlp(argv[2]);
    std::string config,output;
    for(int i=1;i<argc;i++) {
      std::string a=argv[i];
      if(a=="--config"&&i+1<argc)config=argv[++i];
      else if(a=="--output"&&i+1<argc)output=argv[++i];
      else throw std::runtime_error("usage: pim_vla_sim --config file.json --output directory");
    }
    PimVla::require(!config.empty()&&!output.empty(),"--config and --output required");
    return PimVla::run(config,output);
  }catch(const std::exception& e){std::cerr<<"ERROR: "<<e.what()<<"\n";return 1;}
}
