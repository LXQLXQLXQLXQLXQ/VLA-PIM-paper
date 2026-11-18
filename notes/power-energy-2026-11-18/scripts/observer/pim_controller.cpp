#include "ramulator/controller/impl/pim_model.h"
#include <bit>
#include <cmath>
#include <limits>

namespace PimVla {
namespace {
Clock node_ready(const DRAMNode* n,int cmd,const AddrVec_t& a) {
  Clock result=n->m_cmd_ready_clk[cmd];
  if(n->m_child_nodes.empty()) return result;
  int child=a[n->m_level+1];
  if(child>=0) return std::max(result,node_ready(n->m_child_nodes.at(child).get(),cmd,a));
  for(const auto& c:n->m_child_nodes) result=std::max(result,node_ready(c.get(),cmd,a));
  return result;
}
bool starts(const std::string& s,const std::string& p) {return s.rfind(p,0)==0;}
bool is_mac(const std::string& n) {return starts(n,"MACAB")||starts(n,"MACQK");}
enum RDOpcode {
  MAC=0, MAC_INIT=1, MAC_RED=2, MAC_INIT_RED=3, MAC_INIT_RED_LOW=4,
  MAC_INIT_RED_HIGH=5, RD_ROPE=6, RD_ROPE_Q=7, RD_ROPE_K=8
};
enum WROpcode { WB_ACC=0, WB_MAC=1, WB_OBUF=3 };
constexpr int SRF_BANK_SELECT_BIT=32;

int qk_opcode(const Operation& op) {
  if(op.lanes==16&&op.weight_lane_offset==0)return MAC_INIT_RED;
  require(op.lanes==8&&(op.weight_lane_offset==0||op.weight_lane_offset==8),
          "QK column must select the whole, low half, or high half");
  return op.weight_lane_offset==0?MAC_INIT_RED_LOW:MAC_INIT_RED_HIGH;
}
}

std::vector<Operation> parse_operations(const ConfigNode& node) {
  std::vector<Operation> result; result.reserve(node.size());
  for(const auto& x:node.seq()) {
    Operation o; o.name=x["op"].as<std::string>();o.id=x["id"].as<int>(result.size());
    require(o.id==static_cast<int>(result.size()),"program IDs must be contiguous");
    const auto address=x["addr"];
    for(const auto& a:address.seq()) o.addr.push_back(a.as<int>());
    const auto spill=x["spill_addr"];
    if(spill)for(const auto& a:spill.seq())o.spill_addr.push_back(a.as<int>());
    require(o.addr.size()==6,"physical address must have 6 levels");
    require(o.addr[1]==1,"PIM may only access rank1");
    o.slot=x["slot"].as<int>(0); o.result_slot=x["result_slot"].as<int>(0);
    o.rows=x["rows"].as<int>(1);o.pairs=x["pairs"].as<int>(1);
    o.epoch=x["epoch"].as<std::string>("");
    o.dest_slot=x["dest_slot"].as<int>(-1);o.source_bank=x["source_bank"].as<int>(0);
    o.tensor_fragment=x["tensor_fragment"].as<int>(-1);o.output_columns=x["output_columns"].as<int>(1);
    o.output_column=x["output_column"].as<int>(0);o.fragment=x["fragment"].as<int>(0);
    o.output_tile=x["output_tile"].as<int>(0);o.kv_token=x["kv_token"].as<int>(0);
    o.reduction_word=x["reduction_word"].as<int>(16);
    o.lanes=x["lanes"].as<int>(16);o.elements=x["elements"].as<int>(16);
    o.weight_lane_offset=x["weight_lane_offset"].as<int>(0);
    o.bytes=x["bytes"].as<int>(32);o.token=x["token"].as<int>(0);
    o.release_result=x["release_result"].as<bool>(false);
    o.dest=x["dest"].as<std::string>("");o.source=x["source"].as<std::string>("");
    const auto regions=x["source_regions"];
    if(regions)for(const auto& r:regions.seq())o.source_regions.push_back({r["bank"].as<int>(),r["byte_offset"].as<int>(),r["bytes"].as<int>()});
    require(o.slot>=0&&o.slot<32,"SRF capacity exceeded");
    require(o.result_slot>=0&&o.result_slot<64,"output pool capacity exceeded");
    require(o.reduction_word>=16&&o.reduction_word<512,"reduction outside bank output pool");
    const auto deps=x["deps"];
    if(deps) for(const auto& d:deps.seq()) {
      int i=d.as<int>(); require(i>=0&&i<o.id,"dependency must point to previous request");o.deps.push_back(i);
    }
    const auto issue_deps=x["issue_deps"];
    if(issue_deps)for(const auto& d:issue_deps.seq()) {
      int i=d.as<int>();require(i>=0&&i<o.id,"issue dependency must point to previous request");o.issue_deps.push_back(i);
    }
    if(x["children"]) o.children=parse_operations(x["children"]);
    result.push_back(std::move(o));
  }
  return result;
}

PIMController::PIMController(int ch,const ConfigNode& spec_cfg,const ConfigNode& metadata):channel(ch) {
  ConfigNode cfg=spec_cfg["dram"]?spec_cfg:ConfigNode(ConfigNode::Map{{"dram",spec_cfg}});
  std::string impl=cfg["dram"]["impl"].as<std::string>("LPDDR5XPIM");
  device.init(DRAMSpec::create(impl,cfg));device.set_channel_id(ch);
  mc_control=metadata["mc_command_control"].as<bool>(false);
  batch_array_commands=mc_control&&metadata["batch_pim_columns"].as<bool>(false);
  info.resize(device.m_spec->command_count);
  gpu_command_counts.resize(device.m_spec->command_count,0);
  for(int cmd=0;cmd<device.m_spec->command_count;cmd++) {
    const auto& name=device.m_spec->command_names[cmd];auto m=metadata["commands"][name];
    // Older exported specs predate the row-independent selector.
    if(name=="SRF_SELECT") {
      if(!m)continue;
      srf_select_cmd=cmd;
    }
    require(static_cast<bool>(m),"spec metadata missing command "+name);
    auto& v=info[cmd];v.latency=m["latency"].as<int>(0);v.burst=m["burst"].as<int>(0);
    v.completion=m["completion"].as<int>(1);v.external_ca=m["external_ca"].as<int>(1);
    v.private_ca=m["private_ca"].as<int>(0);auto dir=m["direction"].as<std::string>("");
    v.direction=dir.empty()?0:dir[0];
    v.wire_command=m["wire_command"].as<std::string>(name);
  }
  checker.spec=device.m_spec;checker.info=&info;
  lookahead=std::make_unique<NativeLookahead>(ch,spec_cfg);
  for(int rank=0;rank<2;++rank)refresh_due[rank]=refresh_interval(rank);
}
Clock PIMController::refresh_interval(int rank) const {
  return device.m_spec->get_timing_value(refresh_all_bank.at(rank)?"nREFI":"nREFIpb");
}
Clock PIMController::ready_at(int cmd,const AddrVec_t& addr,uint16_t bank_mask) const {
  if(bank_mask)return std::max<Clock>(0,device.masked_ready_at(cmd,addr,bank_mask));
  Clock at=node_ready(device.m_root.get(),cmd,addr);
  if(device.m_spec->bank_targets[cmd]==BankTarget::Pair)
    at=std::max(at,node_ready(device.m_root.get(),cmd,device.partner_addr_vec(cmd,addr)));
  return std::max<Clock>(0,at);
}
Clock PIMController::spacing(int pre,const AddrVec_t& a,int following,const AddrVec_t& b) const {
  // Query the spec's own pair constraints, including rank siblings and BG
  // broadcasts. This is a policy prediction, never an alternative legality test.
  Clock answer=0;
  bool ancestors_same=true;
  for(int level=0;level<=device.m_bank_level && ancestors_same;level++) {
    bool same=(a[level]==b[level]||a[level]<0||b[level]<0);
    for(const auto& t:device.m_spec->timing_cons[level][pre]) {
      if(t.cmd==following && t.window==1 && t.sibling!=same) answer=std::max<Clock>(answer,t.val);
    }
    ancestors_same=same;
  }
  return answer;
}
int PIMController::command(const Operation& op,bool local) const {
  std::string name=op.name;
  if(is_mac(name)) name+="_M"+std::to_string(op.rows);
  if(local && device.m_spec->has_command(name+"_LOCAL")) name+="_LOCAL";
  return device.m_spec->get_command_id(name);
}
void PIMController::set_stage(const std::vector<Operation>& ops,int stage_id,Clock clk,const std::string& name) {
  require(stage_finished(clk),"replacing a live PIM stage");
  stage=stage_id;top.reset(&ops,clk);inner.reset(nullptr,clk);descriptor_index=-1;epoch_owned=false;pim_arrival=clk;
  exclusive_q_exchange=fused&&!ops.empty()&&ops.front().epoch=="q_exchange_exclusive";
  checker.set_stage(clk,stage_id);
  if(power_stats)power_stats->set_stage(clk,stage_id);
  resources.start_stage(name,clk);
  if(mc_control) {
    input_rows.clear();
    auto collect=[&](auto&& self,const std::vector<Operation>& sequence)->void {
      for(size_t i=0;i<sequence.size();++i) {
        const auto& op=sequence[i];
        if(op.name=="LOCALRD" && i+1<sequence.size() && sequence[i+1].name=="BCAST")
          input_rows.emplace(4*op.addr[2]+op.addr[3],op.addr[4]+row_offset);
        if(!op.children.empty())self(self,op.children);
      }
    };
    collect(collect,ops);
  }
  forecast_dirty=true;
}
void PIMController::begin_kernel(const Kernel* k,Clock clk) {
  require(!kernel && queued_gpu==0&&gpu_outstanding==0,"overlapping VLM kernels");
  kernel=k;kernel_reads=(k->reads+15-channel)/16;kernel_writes=(k->writes+15-channel)/16;
  kernel_total=kernel_reads+kernel_writes;kernel_next=issued_reads=issued_writes=0;now=clk;
  kernel_write_base=k->base+(std::max(k->reads,k->read_address_extent_sectors)+15)/16*16;
  kernel_memory_done=clk;
}
void PIMController::end_kernel() {require(kernel_finished(),"kernel still has requests");kernel=nullptr;}
void PIMController::reset_serial_epoch(Clock origin) {
  // Case b is defined as the concatenation of independently initialized solo
  // measurements. Reset device state at the epoch boundary, never elapsed
  // time or measured durations. Concurrent cases never take this path.
  require(!kernel&&gpu_outstanding==0&&stage_finished(origin),"serial epoch reset has live work");
  checker.advance(origin);checker.bursts.clear();
  checker.external_start=checker.external_end=checker.private_end=origin;
  checker.private_start=origin;
  device.m_bank_nodes.clear();
  device.m_root=std::make_unique<DRAMNode>(device.m_spec,nullptr,0,channel);
  device.m_root->for_each_at_level(device.m_bank_level,[&](DRAMNode* b){device.m_bank_nodes.push_back(b);});
  for(int rank=0;rank<2;++rank)refresh_due[rank]=origin+refresh_interval(rank);
  refresh_bank.fill(0);pending_act={PendingAct{},PendingAct{}};
  external_free=private_free=gpu_dq_end=pim_dq_end=origin;
  pim_mode=false;srf_write_selected=false;exclusive_q_exchange=false;
  all_bank_row=-1;broadcast_addr.clear();export_store_done=-1;
  forecast_dirty=true;gap_write_phase=false;write_drain=false;
}
bool PIMController::kernel_finished() const {return !kernel || (kernel_next>=kernel_total&&gpu_outstanding==0);}
bool PIMController::stage_finished(Clock clk) const {
  return top.issued()&&inner.issued()&&descriptor_index<0&&top.tail<=clk;
}
Clock PIMController::coarse_upload_ready() const {
  if(coarse_descriptor<0||descriptor_index!=coarse_descriptor)return NEVER;
  return std::max(descriptor_ready,pim_dq_end);
}
Clock PIMController::coarse_result_ready() const {
  if(coarse_descriptor<0)return NEVER;
  if(descriptor_index==coarse_descriptor&&inner.issued())return inner.tail;
  return top.done.at(coarse_descriptor);
}
void PIMController::settle_coarse(Clock clk) {
  // Completion-only work must precede the host's same-CK kernel admission.
  // next_pim may consume satisfied zero-time barriers, but never issues a
  // hardware command. Pending native commands still go through step/issue.
  if(coarse_phase==1&&descriptor_index>=0&&
     (inner.issued()||inner.ops->at(inner.next).name=="BARRIER")) {
    now=clk;(void)next_pim(clk);
  }
}
void PIMController::retire_and_fill(Clock clk,bool permit_gpu) {
  while(!completions.empty()&&completions.top().at<=clk) {
    if(completions.top().gpu) {
      --gpu_outstanding;
      kernel_memory_done=completions.top().at;
    }
    completions.pop();
  }
  checker.retire(clk);
  if(!kernel||!permit_gpu) return;
  const int limit=kernel->mlp ? kernel->mlp : window;
  while(kernel_next<kernel_total&&gpu_outstanding<limit) {
    Clock release=clk;
    if(!kernel->mlp)
      release=kernel->start+kernel->paused+static_cast<Clock>((static_cast<long double>(kernel_next)*kernel->nominal)/kernel_total);
    if(release>clk) break;
    uint64_t i=kernel_next;
    bool wr=(static_cast<__uint128_t>(i+1)*kernel_writes/kernel_total)>(static_cast<__uint128_t>(i)*kernel_writes/kernel_total);
    uint64_t physical=wr?kernel_write_base+channel+16*issued_writes++
                        :kernel->base+channel+16*issued_reads++;
    require(physical%16==static_cast<uint64_t>(channel),"GPU address/channel mismatch");
    uint64_t intra=physical/16;int col=intra%64;uint64_t b=intra/64;
    int bank=b%16;int row=(b/16)%device.m_spec->organization.level_sizes[4];
    AddrVec_t a={channel,0,bank/4,bank%4,row,col};
    int cmd=device.m_spec->get_command_id(wr?"WR":"RD");
    gpu_queues[bank*2+wr].push_back({a,cmd,i,release});++queued_gpu;++gpu_outstanding;++kernel_next;if(wr)++queued_writes;
  }
}
Clock PIMController::dependencies(const Operation& op,const Cursor& cursor) const {
  Clock at=0;for(int d:op.deps) at=std::max(at,cursor.done.at(d));return at;
}
Candidate PIMController::make_candidate(int final,const AddrVec_t& addr,Candidate::Source src,
                                        Clock earliest,bool local,uint16_t bank_mask) {
  Candidate c;c.source=src;c.local=local;
  int cmd=device.get_preq_command(final,addr,std::max(now,earliest),bank_mask);
  c.addr=device.preq_addr_vec(final,cmd,addr,std::max(now,earliest),bank_mask);
  if(local) {
    const auto& n=device.m_spec->command_names[cmd];
    if(device.m_spec->has_command(n+"_LOCAL")) cmd=device.m_spec->get_command_id(n+"_LOCAL");
  }
  c.cmd=cmd;c.final=cmd==final;c.rowhit=c.final;
  c.at=std::max({now,earliest,ready_at(cmd,c.addr,c.final?bank_mask:0)});
  if(starts(device.m_spec->command_names[cmd],"ACT1")) {
    int cmd2=device.m_spec->get_command_id(local?"ACT2_LOCAL":"ACT2");
    c.at=std::max(c.at,ready_at(cmd2,c.addr)-device.m_spec->get_timing_value("nAAD"));
  }
  const auto& m=info[cmd];
  if(m.external_ca)c.at=std::max(c.at,external_free);
  if(m.private_ca)c.at=std::max(c.at,private_free);
  // ACT-2 is owned by the request that issued ACT-1; reserve its deadline.
  for(const auto& p:pending_act) if(p.cmd>=0) {
    bool shared=(m.external_ca&&info[p.cmd].external_ca)||(m.private_ca&&info[p.cmd].private_ca);
    if(shared && cmd!=p.cmd && c.at<p.deadline && c.at+std::max(m.external_ca,m.private_ca)>p.deadline)
      c.at=p.deadline+1;
    // An external PRE/REF may interfere with a privately activated bank too.
    if(cmd!=p.cmd&&c.at+spacing(cmd,c.addr,p.cmd,p.addr)>p.deadline)c.at=std::max(c.at,p.deadline+1);
  }
  return c;
}

Candidate PIMController::prepare_mc_request(const Operation& op,AddrVec_t addr,Clock earliest,
                                            bool broadcast_read,int command_id,uint16_t bank_mask) {
  auto id=[&](const char* name){return device.m_spec->get_command_id(name);};
  auto preq=[&](const char* name,const AddrVec_t& target,Clock ready) {
    auto c=make_candidate(id(name),target,Candidate::PIM,ready);
    c.final=false;c.rowhit=false;
    return c;
  };
  const int last_row=device.m_spec->organization.level_sizes[4]-1;
  const bool input_from_host=op.name=="WRGB";
  const bool independent_srf=srf_select_cmd>=0;
  const bool exporting=op.name=="RDRES";
  const bool host_read=exporting&&export_store_done>=0;
  const bool target_pim=!(op.name=="RD"||op.name=="WR"||host_read);
  if(exporting) {
    require(op.spill_addr.size()==6,"MC protocol requires an accumulator spill address");
    addr=op.spill_addr;
    addr[4]+=row_offset;
    if(host_read)earliest=std::max(earliest,export_store_done);
  }
  const AddrVec_t host_register_row={channel,1,-1,-1,last_row-2,-1};
  AddrVec_t requested_broadcast;
  if(input_from_host&&!independent_srf)requested_broadcast=host_register_row;
  const bool store_into_input=target_pim&&addr[2]>=0&&(op.name=="LOCALWR"||exporting)&&
                              input_rows.contains({4*addr[2]+addr[3],addr[4]});
  if(broadcast_read||store_into_input) {
    requested_broadcast=addr;
    requested_broadcast[5]=-1;
  }
  const bool transition=target_pim!=pim_mode;
  if(!broadcast_addr.empty()&&(transition||requested_broadcast!=broadcast_addr)) {
    const auto close=broadcast_addr;
    return preq(close[2]<0?"PREab":"PREpb",close,std::max(earliest,pim_dq_end));
  }
  if(transition) {
    AddrVec_t selector={channel,1,0,target_pim?0:1,target_pim?last_row:last_row-1,-1};
    Clock ready=std::max(earliest,pim_dq_end);
    const bool open=device.check_rowbuffer_hit(id("RD"),selector,now);
    return preq(open?"PREpb":"RD",selector,ready);
  }
  if(input_from_host) {
    require(op.source!="host_query"||independent_srf,"Host Q write requires bank-addressed SRF writes");
    if(independent_srf&&!srf_write_selected)
      return preq("SRF_SELECT",host_register_row,earliest);
    if(!independent_srf&&broadcast_addr.empty())return preq("ACTAB",host_register_row,earliest);
    addr=host_register_row;
    addr[5]=op.slot;
    if(op.source=="host_query") {
      addr[2]=op.addr[2];
      addr[3]=op.addr[3];
      addr[5]|=SRF_BANK_SELECT_BIT;
    }
    if(!independent_srf)earliest=std::max(earliest,ready_at(id("WR"),addr));
  }
  if(target_pim&&addr[2]>=0&&addr[4]==all_bank_row) {
    AddrVec_t target={channel,1,-1,-1,all_bank_row,-1};
    return preq("PREab",target,earliest);
  }
  if(broadcast_read && broadcast_addr.empty() &&
     device.check_rowbuffer_hit(id("RD"),addr,now))
    return preq("PREpb",addr,earliest);
  const int cmd=exporting?id(host_read?"RD":"LOCALWR"):command_id;
  return make_candidate(cmd,addr,Candidate::PIM,earliest,false,bank_mask);
}

void PIMController::update_mc_mode(int cmd,const AddrVec_t& addr) {
  if(!mc_control||addr[1]!=1)return;
  const auto& name=device.m_spec->command_names[cmd];
  const int last_row=device.m_spec->organization.level_sizes[4]-1;
  const bool has_broadcast=!broadcast_addr.empty();
  if(name=="ACT2"&&pim_mode&&input_rows.contains({4*addr[2]+addr[3],addr[4]})) {
    require(!has_broadcast,"broadcast source activated with another broadcast open");
    broadcast_addr=addr;
    broadcast_addr[5]=-1;
  } else if(name=="SRF_SELECT") {
    require(pim_mode&&!has_broadcast&&addr[4]==last_row-2,"invalid SRF write selector");
    srf_write_selected=true;
  } else if(name=="ACTAB") {
    require(pim_mode&&!has_broadcast,"ACTAB requires MB idle");
    all_bank_row=addr[4];
    if(addr[4]==last_row-2)broadcast_addr=addr;
  } else if(name=="PREab") {
    broadcast_addr.clear();
    all_bank_row=-1;
  } else if(name=="PREpb") {
    all_bank_row=-1;
    if(has_broadcast&&addr[2]==broadcast_addr[2]&&addr[3]==broadcast_addr[3])broadcast_addr.clear();
    if(addr[2]==0&&(addr[3]==0||addr[3]==1)) {
      AddrVec_t selector={channel,1,0,addr[3],last_row-addr[3],-1};
      if(device.check_rowbuffer_hit(device.m_spec->get_command_id("RD"),selector,now)) {
        pim_mode=addr[3]==0;
        srf_write_selected=false;
      }
    }
  } else if(name=="RD"||name=="WR") {
    require(!pim_mode,"DRAM host column command issued in PIM mode");
  } else if(name=="WRGB") {
    require(pim_mode&&((srf_write_selected&&!has_broadcast)||
            (has_broadcast&&broadcast_addr[4]==last_row-2)),
            "Host SRF write requires the register selector");
  } else if(is_mac(name)||starts(name,"LOCALWR")) {
    const bool input_store=name=="LOCALWR"&&has_broadcast&&
        broadcast_addr[2]==addr[2]&&broadcast_addr[3]==addr[3]&&broadcast_addr[4]==addr[4];
    require(pim_mode&&(!has_broadcast||input_store),"MAC/store does not match the current rank state");
    if(addr[2]<0)require(all_bank_row==addr[4],"all-bank column requires ACTAB");
  } else if(name=="LOCALRD_LOCAL") {
    require(pim_mode&&!has_broadcast&&addr[2]<0&&all_bank_row==addr[4],
            "all-bank RoPE read requires its active data row");
  } else if(name=="LOCALRD") {
    require(pim_mode&&(!has_broadcast||
            (broadcast_addr[2]==addr[2]&&broadcast_addr[3]==addr[3]&&broadcast_addr[4]==addr[4])),
            "PIM column read does not match the current rank state");
  }
}

Candidate PIMController::next_pim(Clock clk) {
  // FIFO32 is decoded storage, not an out-of-order issue window. Only the
  // head may issue, including its native ACT/PRE prerequisites. Advancing on
  // issue still permits independent operations to overlap their completions.
  if(descriptor_index>=0 && inner.issued() && inner.tail<=clk) {
    top.done[descriptor_index]=inner.tail;top.tail=std::max(top.tail,inner.tail);
    descriptor_index=-1;inner.reset(nullptr,clk);
  }
  if(coarse_phase==0&&descriptor_index>=0) {
    Candidate wait;wait.at=coarse_upload_ready()>clk?coarse_upload_ready():NEVER;
    return wait;
  }
  if(coarse_phase==1&&descriptor_index<0)return {};
  Cursor& cursor=descriptor_index>=0?inner:top;
  if(cursor.issued()) return {};
  require(cursor.next<cursor.decoded_until&&cursor.decoded_until-cursor.next<=32,"instruction FIFO capacity exceeded");
  bool local=descriptor_index>=0;
  const Operation& op=cursor.ops->at(cursor.next);
  Clock at=0;
  if(local)at=std::max(at,descriptor_ready);
  if(op.name=="BARRIER") {
    at=std::max({at,cursor.tail,dependencies(op,cursor)});
    if(at<=clk) {cursor.mark(cursor.next,clk);forecast_dirty=true;return next_pim(clk);}
    Candidate wait;wait.source=Candidate::PIM;wait.at=at;
    return wait;
  }
  if(mc_control&&op.name=="ACTAB"&&std::max(at,dependencies(op,cursor))<=clk) {
    // The old program's fused Down pre-activation is superseded by the
    // broadcast ACTs and the full-bank weight prerequisite of the MAC read.
    cursor.mark(cursor.next,clk);forecast_dirty=true;return next_pim(clk);
  }
  int cmd=command(op,local&&!mc_control);
  size_t group=1;
  int opcode=-1;
  uint16_t mask=0;
  const bool rope_load=op.name=="LOCALRD"&&(op.dest=="rope_coefficient"||op.dest=="rope_input");
  const bool rope_store=op.name=="LOCALWR"&&op.source=="rope_output";
  if(mc_control&&(rope_load||rope_store||(op.name=="LOCALWR"&&
                  (op.source=="qkv_output"||op.source=="reduction_output"||op.source=="fused_result")))) {
    const size_t required=op.source=="reduction_output"?2:16;
    if(cursor.next+required<=cursor.decoded_until) {
      for(size_t i=0;i<required;++i) {
        const auto& store=cursor.ops->at(cursor.next+i);
        if(store.name!=op.name||store.source!=op.source||store.dest!=op.dest||
           ((rope_load||rope_store)&&(store.slot!=op.slot||store.token!=op.token))||
           store.addr[4]!=op.addr[4]||
           store.addr[5]!=op.addr[5]||store.addr[2]<0||store.addr[2]>=4||
           store.addr[3]<0||store.addr[3]>=4)break;
        mask|=1u<<(4*store.addr[2]+store.addr[3]);
      }
      if(mask==(required==2?0x11:0xffff)) {
        group=required;
        if(rope_load) {
          opcode=op.dest=="rope_coefficient"?RD_ROPE:(op.slot==0?RD_ROPE_Q:RD_ROPE_K);
          cmd=device.m_spec->get_command_id("LOCALRD_LOCAL");
        } else {
          opcode=op.source=="qkv_output"?WB_ACC:WB_OBUF;
          cmd=device.m_spec->get_command_id("LOCALWR_LOCAL");
        }
      }
    }
    require(!(rope_load||rope_store)||group==16,"RoPE array command requires one column in every bank");
    require(op.source!="fused_result"||group==16,"fused output requires one packet in every bank");
    if(group==1)mask=0;
  }
  const bool mac=is_mac(op.name);
  if(mc_control&&mac) {
    opcode=op.name=="MACQK"?qk_opcode(op):(op.fragment==0?MAC_INIT:MAC);
    mask=0xffff;
  }
  const bool array_batch=batch_array_commands&&mask==0xffff;
  const uint16_t remaining=mask&~cursor.issued_banks;
  // One CA column command selects the same BA in each BG, matching ACTAB's
  // activation batches. Keep the logical operation at the FIFO head.
  require(!array_batch||remaining,"finished bank batch left at FIFO head");
  const uint16_t issue_mask=array_batch?(0x1111u<<std::countr_zero(remaining)):mask;
  auto in_batch=[&](const Operation& part) {
    return !array_batch||group==1||(issue_mask&(1u<<(4*part.addr[2]+part.addr[3])));
  };
  for(size_t i=0;i<group;++i) {
    const auto& part=cursor.ops->at(cursor.next+i);
    if(!in_batch(part))continue;
    at=std::max(at,dependencies(part,cursor));
    for(int d:part.issue_deps)if(!cursor.dispatched.at(d))at=NEVER;
  }
  // Future producer output is validated once this batch's dependencies finish.
  if(at>clk) {
    Candidate wait;wait.source=Candidate::PIM;wait.at=at;
    if(policy=="gap_batch"&&!legacy_gap_batch)wait.addr=op.addr;
    return wait;
  }
  try {
    if(export_store_done<0&&group==1)
      at=std::max(at,resources.ready(op,clk,array_batch?issue_mask:0xffff));
    for(size_t i=0;i<group&&group>1;++i) {
      const auto& part=cursor.ops->at(cursor.next+i);
      if(in_batch(part))at=std::max(at,resources.ready(part,clk));
    }
  }
  catch(const std::exception& e){throw std::runtime_error(std::string(e.what())+" op="+op.name+" id="+std::to_string(op.id)+" stage="+std::to_string(stage));}
  AddrVec_t physical=op.addr;physical[4]+=row_offset;
  if(group>1)physical[2]=physical[3]=-1;
  require(physical[4]<device.m_spec->organization.level_sizes[4],"PIM layer address exceeds rank capacity");
  const bool broadcast_read=op.name=="LOCALRD" && cursor.next+1<cursor.ops->size() &&
                            cursor.ops->at(cursor.next+1).name=="BCAST";
  const bool mc_array=mc_control&&(info[cmd].external_ca||op.name=="RDRES");
  // A refresh may have closed the row since the preceding batch. Reopen a
  // rank-wide row through the normal prerequisites before issuing this mask.
  const uint16_t array_mask=issue_mask==0xffff?0:issue_mask;
  Candidate c=mc_array?prepare_mc_request(op,physical,at,broadcast_read,cmd,array_mask):
                       make_candidate(cmd,physical,Candidate::PIM,at,local&&!mc_control);
  if(mc_control&&c.final) {
    c.opcode=opcode;c.group=group;c.bank_mask=issue_mask;
    if(array_batch)c.pending_banks=remaining&~issue_mask;
  }
  c.arrival=pim_arrival;c.dependency_ready=at<=clk;c.index=cursor.next;
  if(fused&&info[cmd].direction)c.at=std::max(c.at,gpu_dq_end);
  if(blocked_by_owner(c,clk))return {};
  return c;
}
bool PIMController::blocked_by_owner(const Candidate& c,Clock clk) const {
  if(c.cmd<0)return true;
  if(c.source==Candidate::PIM&&refresh_due[1]<=clk)return true;
  const auto& name=device.m_spec->command_names[c.cmd];
  if(starts(name,"ACT2"))return true; // issued only by the owned ACT2 path
  if(starts(name,"ACT1")&&pending_act[info[c.cmd].private_ca?1:0].cmd>=0)return true;
  return false;
}
Candidate PIMController::next_gpu(Clock clk) {
  if(!queued_gpu)return {};
  if(external_free>clk){Candidate c;c.at=external_free;return c;}
  Candidate best;int writes=queued_writes;
  if(writes>=write_high)write_drain=true;
  if(writes<=write_low)write_drain=false;
  bool desired_write=write_drain;
  if(policy=="gap_batch"&&!(top.issued()&&inner.issued())) {
    if(!legacy_gap_batch&&!writes)gap_write_phase=false;
    if(!gap_write_phase&&queued_gpu==writes)gap_write_phase=true;
    desired_write=gap_write_phase;
    if(desired_write&&!writes)return {};
  }
  bool any_desired=desired_write?writes>0:queued_gpu>writes;
  for(size_t i=0;i<gpu_queues.size();i++) {
    if(gpu_queues[i].empty())continue;
    const auto& q=gpu_queues[i].front();
    if(refresh_due[0]<=clk && (q.addr[2]*4+q.addr[3])%8==refresh_bank[0])continue;
    if(any_desired&&((info[q.cmd].direction=='W')!=desired_write))continue;
    int cmd=device.get_preq_command(q.cmd,q.addr,clk);
    Candidate candidate;
    candidate.cmd=cmd;candidate.addr=q.addr;candidate.source=Candidate::GPU;
    candidate.index=i;candidate.arrival=q.arrival;
    // Filter ownership before ranking bank heads. Otherwise an older ACT1
    // can win while the external ACT2 lane is occupied, then be rejected by
    // can_issue without considering another bank's ready PRE/RD/WR. ACT2 is
    // exclusively served by the owned path, which also supplies its wakeup.
    if(blocked_by_owner(candidate,clk))continue;
    Clock at=std::max({clk,q.arrival,ready_at(cmd,q.addr),external_free});
    if(device.m_spec->command_meta[cmd].is_opening && device.m_spec->command_names[cmd]=="ACT1")
      at=std::max(at,ready_at(device.m_spec->get_command_id("ACT2"),q.addr)-device.m_spec->get_timing_value("nAAD"));
    for(const auto& p:pending_act)if(p.cmd>=0&&cmd!=p.cmd && at+spacing(cmd,q.addr,p.cmd,p.addr)>p.deadline)at=std::max(at,p.deadline+1);
    bool hit=(cmd==q.cmd),ready=at<=clk,best_ready=best.at<=clk;
    if(best.cmd<0 || (ready&&!best_ready) || (ready&&best_ready&&(hit>best.rowhit || (hit==best.rowhit&&q.arrival<best.arrival))) || (!ready&&!best_ready&&at<best.at)) {
      candidate.at=at;candidate.final=hit;candidate.rowhit=hit;
      best=std::move(candidate);
    }
  }
  return best;
}
Candidate PIMController::next_refresh(Clock clk) {
  Candidate best;
  for(int rank=0;rank<2;rank++) if(refresh_due[rank]<=clk) {
    int bank=refresh_bank[rank];AddrVec_t a={channel,rank,bank/4,bank%4,-1,-1};
    int cmd=device.m_spec->get_command_id(refresh_all_bank[rank]?"REFab":"REFpb");
    if(refresh_all_bank[rank])a[2]=a[3]=-1;
    auto c=make_candidate(cmd,a,Candidate::REFRESH,refresh_due[rank]);c.index=rank;
    if(c.at<best.at)best=c;
  }
  return best;
}
bool PIMController::protect_pim(const Candidate& g,const Candidate& p,Clock clk) {
  if(g.cmd<0)return false;
  if(policy=="pim_head")return p.cmd>=0&&p.dependency_ready&&clk+spacing(g.cmd,g.addr,p.cmd,p.addr)>p.at;
  if(policy=="frfcfs")return false;
  Clock horizon=device.m_spec->get_timing_value("nCL")+device.m_spec->get_timing_value("nBL_min")+device.m_spec->get_timing_value("nCS");
  if(policy=="pim_lookahead") {
    const Cursor& cur=descriptor_index>=0?inner:top;
    if(!cur.ops||cur.issued())return false;
    bool expired=forecast_time<0||clk>forecast_time+horizon||(!forecast.empty()&&forecast.front().at<clk);
    if(forecast_dirty||expired) {
      forecast=lookahead->predict(device,*cur.ops,cur.next,cur.done,clk,horizon,descriptor_index>=0,row_offset);
      forecast_dirty=false;forecast_time=clk;
    }
    for(const auto& f:forecast)if(clk+spacing(g.cmd,g.addr,f.cmd,f.addr)>f.at)return true;
    return false;
  }
  if(policy=="gap_batch") {
    if(legacy_gap_batch) {
      if(p.cmd<0)return false;
      if(info[p.cmd].direction)return true;
    }
    // A pending barrier has a wake-up time but no DRAM command address.
    if(p.at==NEVER||p.addr.empty())return false;
    // A known dependency wait is a proven idle interval; summing future MAC
    // completions would overstate it because column fetch and compute overlap.
    Clock gap=std::max<Clock>(0,p.at-clk);
    int wrgb=device.m_spec->get_command_id("WRGB"),rdres=device.m_spec->get_command_id("RDRES");
    Clock minimum=std::max(spacing(g.cmd,g.addr,wrgb,p.addr)+spacing(wrgb,p.addr,g.cmd,g.addr),
                           spacing(g.cmd,g.addr,rdres,p.addr)+spacing(rdres,p.addr,g.cmd,g.addr));
    return gap<minimum;
  }
  throw std::runtime_error("unknown arbitration "+policy);
}
void PIMController::issue(int cmd,const AddrVec_t& addr,Clock clk,int stat_stage,int opcode,uint16_t bank_mask) {
  const auto& n=device.m_spec->command_names[cmd];
  const uint16_t array_mask=mc_control&&addr[1]==1&&opcode>=0&&bank_mask!=0xffff?bank_mask:0;
  if(n=="REFpb"||n=="REFab")
    require((n=="REFab")==refresh_all_bank.at(addr[1]),"refresh command violates fixed rank0 REFpb / rank1 REFab policy");
  if(!device.check_timing(cmd,addr,clk,array_mask))throw std::runtime_error("scheduler bypassed native check_timing "+device.m_spec->command_names[cmd]+" at "+std::to_string(clk));
  int preq=device.get_preq_command(cmd,addr,clk,array_mask);
  if(preq!=cmd)throw std::runtime_error("scheduler bypassed native prerequisite "+device.m_spec->command_names[cmd]+" requires "+device.m_spec->command_names[preq]+" at "+std::to_string(clk)+" rank="+std::to_string(addr[1])+" bg="+std::to_string(addr[2])+" bank="+std::to_string(addr[3])+" row="+std::to_string(addr[4]));
  update_mc_mode(cmd,addr);
  checker.observe(cmd,addr,clk,stat_stage,opcode,bank_mask);
  if(power_stats)power_stats->observe(cmd,addr,clk,array_mask,info[cmd].direction);
  device.issue_command(cmd,addr,clk,array_mask);
  if(n=="REFpb"||n=="REFab")++refresh_counts.at(addr[1])[n=="REFab"];
  if(addr[1]==0)++gpu_command_counts[cmd];
  if(addr[1]==1)forecast_dirty=true;
  const auto& m=info[cmd];
  if(m.external_ca)external_free=clk+m.external_ca;
  if(m.private_ca)private_free=clk+m.private_ca;
  if(n=="ACT1"||n=="ACT1_LOCAL") {
    int lane=m.private_ca?1:0;auto& p=pending_act[lane];
    require(p.cmd<0,"ACT1 issued without ACT2 ownership capacity");
    p.cmd=device.m_spec->get_command_id(n=="ACT1"?"ACT2":"ACT2_LOCAL");p.addr=addr;
    p.deadline=clk+device.m_spec->get_timing_value("nAAD");
  }
  if(n=="ACT2"||n=="ACT2_LOCAL") {
    int lane=m.private_ca?1:0;auto& p=pending_act[lane];
    require(p.cmd==cmd&&p.addr==addr&&clk<=p.deadline,"ACT2 missing owner or late");
    p.cmd=-1;p.deadline=NEVER;
  }
  last_progress=clk;
}
void PIMController::finish_pim(const Candidate& c,Clock clk) {
  Cursor& cursor=descriptor_index>=0?inner:top;
  require(c.index==cursor.next,"PIM command bypassed FIFO head");
  const auto& op=cursor.ops->at(c.index);
  if(!c.final)return;
  int cmd=c.cmd;Clock complete=clk+info[cmd].completion;
  const bool batched=c.pending_banks||cursor.issued_banks;
  if(batched) {
    if(c.group==1)resources.issue(op,clk,complete,c.bank_mask);
    else for(size_t i=0;i<c.group;++i) {
      const auto& part=cursor.ops->at(cursor.next+i);
      if(c.bank_mask&(1u<<(4*part.addr[2]+part.addr[3]))) {
        resources.issue(part,clk,complete);
        cursor.done[cursor.next+i]=complete;
        cursor.dispatched[cursor.next+i]=1;
      }
    }
    cursor.issued_banks|=c.bank_mask;
    cursor.batch_tail=std::max(cursor.batch_tail,complete);
    pim_arrival=clk;
    if(c.pending_banks)return;
    complete=cursor.batch_tail;
    cursor.issued_banks=0;
    cursor.batch_tail=0;
    if(c.group>1) {
      for(size_t i=0;i<c.group;++i) {
        const auto part_complete=cursor.done[cursor.next];
        cursor.dispatched[cursor.next]=0;
        cursor.mark(cursor.next,part_complete);
      }
      return;
    }
  } else if(c.group>1) {
    for(size_t i=0;i<c.group;++i) {
      const auto& store=cursor.ops->at(cursor.next);
      resources.issue(store,clk,complete);
      cursor.mark(cursor.next,complete);
    }
    pim_arrival=clk;
    return;
  }
  if(op.name=="ROPE_EXEC")complete=clk+info[cmd].completion+(op.pairs-1)*device.m_spec->get_timing_value("nROPEII");
  if(mc_control&&op.name=="RDRES") {
    if(export_store_done<0) {
      resources.issue(op,clk,complete);
      export_store_done=complete;
      return;
    }
    export_store_done=-1;
  } else if(!batched)
    resources.issue(op,clk,complete);
  if(info[cmd].direction) { (info[cmd].direction=='R'?pim_read_bytes:pim_write_bytes)+=32;
    pim_dq_end=std::max(pim_dq_end,clk+info[cmd].latency+info[cmd].burst);gap_write_phase=false; }
  size_t index=c.index;cursor.mark(index,complete);
  pim_arrival=clk;
  if(mc_control&&op.name=="MACQK") {
    const auto& reduce=cursor.ops->at(cursor.next);
    require(reduce.name=="REDUCE"&&reduce.kv_token==op.kv_token,"MAC_RED requires its QK reduction");
    require(resources.ready(reduce,complete)==complete,"QK reduction precedes a bank contribution");
    Clock reduced=complete+info[command(reduce,false)].completion;
    resources.issue(reduce,complete,reduced);
    cursor.mark(cursor.next,reduced);
  }
  if(!op.children.empty()) {
    require(descriptor_index<0,"nested descriptors are unsupported");
    descriptor_index=index;descriptor_ready=complete;inner.reset(&op.children,complete);
    top.done[index]=NEVER;
  }
}
Clock PIMController::step(Clock clk,bool permit_gpu,bool release_gpu) {
  now=clk;int outstanding_before=gpu_outstanding;
  const bool permit_release=permit_gpu&&release_gpu;
  retire_and_fill(clk,permit_release);
  if(outstanding_before>0&&(kernel_finished()||(!release_gpu&&gpu_outstanding==0)))return clk;
  bool stage_was_done=stage_finished(clk);
  Candidate pim=next_pim(clk);
  if(!stage_was_done&&stage_finished(clk))return clk;
  // An active fused I/O epoch blocks new GPU issue, but never cancels returns.
  bool epoch=false;
  if(fused) {
    const Cursor& cur=descriptor_index>=0?inner:top;
    if(cur.ops&&!cur.issued()) {
      const auto& op=cur.ops->at(cur.next);
      int cmd=op.name=="BARRIER"?-1:command(op,descriptor_index>=0);
      epoch=(!op.epoch.empty()||(cmd>=0&&info[cmd].direction));
    }
  }
  if(fused&&clk<pim_dq_end)epoch=true;
  if(exclusive_q_exchange&&stage>=0)epoch=true;
  if(checker.epoch_trace)checker.trace_epoch_change(clk,epoch);
  checker.io_epoch=epoch;
  Candidate gpu=permit_gpu&&!epoch?next_gpu(clk):Candidate{};
  Candidate refresh=next_refresh(clk),chosen;
  // nAAD is a maximum ACT1-to-ACT2 distance. Issue the owned ACT2 at
  // its earliest legal opportunity, and never later than its deadline.
  for(int lane=0;lane<2;lane++) {
    auto& a=pending_act[lane];
    if(a.cmd>=0) {
      require(clk<=a.deadline,"missed ACT2 deadline");
      Clock bus_ready=info[a.cmd].private_ca?private_free:external_free;
      if(bus_ready>clk||!device.check_timing(a.cmd,a.addr,clk)) {
        require(clk<a.deadline,"ACT2 not legal at its reserved deadline");continue;
      }
      issue(a.cmd,a.addr,clk,stage);a.cmd=-1;a.deadline=NEVER;return clk;
    }
  }
  auto can_issue=[&](const Candidate& c) {
    if(c.cmd<0||c.at>clk||blocked_by_owner(c,clk))return false;
    const auto& name=device.m_spec->command_names[c.cmd];
    if(starts(name,"ACT1")) {
      // Never start ACT1 if an earlier constraint would prevent ACT2 at nAAD.
      std::string next=info[c.cmd].private_ca?"ACT2_LOCAL":"ACT2";
      int cmd2=device.m_spec->get_command_id(next);
      if(ready_at(cmd2,c.addr)>clk+device.m_spec->get_timing_value("nAAD"))return false;
    }
    return true;
  };
  if(can_issue(refresh))chosen=refresh;
  else if(can_issue(pim)&& (fused||policy!="frfcfs"||!can_issue(gpu)||
      (pim.rowhit&&!gpu.rowhit)||(pim.rowhit==gpu.rowhit&&pim.arrival<=gpu.arrival)))chosen=pim;
  else if(can_issue(gpu)&&!protect_pim(gpu,pim,clk))chosen=gpu;
  else if(can_issue(pim))chosen=pim;
  if(chosen.cmd>=0) {
    issue(chosen.cmd,chosen.addr,clk,stage,chosen.opcode,chosen.bank_mask);
    if(chosen.source==Candidate::GPU&&chosen.final) {
      if(gpu_queues[chosen.index].front().array_preq)++gpu_row_misses;
      else ++gpu_row_hits;
      const auto& m=info[chosen.cmd];Clock done=clk+m.completion;
      completions.push({done,true});gpu_dq_end=std::max(gpu_dq_end,clk+m.latency+m.burst);
      (m.direction=='R'?gpu_read_bytes:gpu_write_bytes)+=32;
      if(m.direction=='W')--queued_writes;
      gpu_queues[chosen.index].pop_front();--queued_gpu;
    } else if(chosen.source==Candidate::GPU)gpu_queues[chosen.index].front().array_preq=true;
    else if(chosen.source==Candidate::PIM)finish_pim(chosen,clk);
    else if(chosen.source==Candidate::REFRESH&&chosen.final) {
      int r=chosen.index;refresh_due[r]+=refresh_interval(r);
      if(!refresh_all_bank[r])refresh_bank[r]=(refresh_bank[r]+1)%8;
    }
    // A private command and an external command can issue in the same CK.
    return clk;
  }
  Clock next=NEVER;
  for(const auto& c:{pim,gpu,refresh})if(c.at>clk)next=std::min(next,c.at);
  if(!completions.empty())next=std::min(next,completions.top().at);
  for(const auto& p:pending_act)if(p.cmd>=0) {
    Clock bus_ready=info[p.cmd].private_ca?private_free:external_free;
    next=std::min(next,std::max({clk+1,ready_at(p.cmd,p.addr),bus_ready}));
    next=std::min(next,p.deadline);
  }
  for(auto due:refresh_due)if(due>clk)next=std::min(next,due);
  if(top.issued()&&top.tail>clk)next=std::min(next,top.tail);
  if(descriptor_index>=0&&inner.issued()&&inner.tail>clk)next=std::min(next,inner.tail);
  if(fused&&pim_dq_end>clk)next=std::min(next,pim_dq_end);
  if(kernel&&!kernel->mlp&&permit_release&&kernel_next<kernel_total&&gpu_outstanding<window)
    next=std::min(next,kernel->start+kernel->paused+static_cast<Clock>((static_cast<long double>(kernel_next)*kernel->nominal)/kernel_total));
  // A candidate blocked by ownership can become issuable after the owned ACT2.
  if(next<=clk)next=clk+1;
  require(next<NEVER,"controller deadlock");
  return next;
}
}
