#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <ostream>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>
#include "ramulator/dram/device.h"

namespace PimVla {
// A passive ledger. It never queries or changes scheduler readiness. Compound
// commands are observed at their primitive's effective timestamp, even though
// the native device exposes their future state immediately on command issue.
class DramPowerStats {
 public:
  using Time = int64_t;
  enum State { Precharged, Activating, Active, Precharging, Refreshing, StateCount };
  struct Bank {
    State state=Precharged;
    Time since=0;
    uint64_t generation=0,reads=0,writes=0,activations=0,precharges=0,refpb=0,refab=0;
    std::array<uint64_t,StateCount> cycles{};
  };
  struct Rank {
    uint64_t reads=0,writes=0,activations=0,precharges=0,refpb_banks=0,refab_banks=0,io_reads=0,io_writes=0;
    std::array<uint64_t,StateCount> bank_cycles{};
    // These histograms each sum to elapsed rank-clock time, not bank time.
    std::array<uint64_t,17> active_banks_ck{},refresh_banks_ck{},active_or_refresh_banks_ck{};
    std::vector<uint64_t> native_commands,primitive_commands;
  };
  using Stage=std::array<Rank,2>;
  const Ramulator::DRAMDevice* device;
  std::array<Bank,32> banks{};
  std::map<int,Stage> stages;
  Time elapsed=0;

  explicit DramPowerStats(const Ramulator::DRAMDevice& d):device(&d) {
    if(d.m_bank_nodes.size()!=32)throw std::runtime_error("power stats requires two ranks of 16 banks");
    classes.resize(d.m_spec->command_count);
    for(int i=0;i<d.m_spec->command_count;++i) {
      const auto& n=d.m_spec->command_names[i];auto& c=classes[i];
      if(n=="ACT1"||n=="ACT1_LOCAL")c=Act1;
      else if(n=="ACT2"||n=="ACT2_LOCAL"||n=="ACT2_PULSE")c=Act2;
      else if(n=="ACTAB"||n=="ACTAB_LOCAL")c=ActAll;
      else if(n=="PREpb"||n=="PREpb_LOCAL"||n=="PREab"||n=="PREab_LOCAL")c=Pre;
      else if(n=="REFpb")c=RefPerBank;
      else if(n=="REFab")c=RefAllBank;
      else if(d.m_spec->command_meta[i].is_accessing) {
        if(n=="WR"||n=="WRA"||n.starts_with("LOCALWR"))c=Write;
        else c=Read;
      }
    }
    current=&stage(-1);
  }

  void observe(int command,const Ramulator::AddrVec_t& address,Time now,uint16_t mask,char io_direction) {
    advance(now);
    auto& r=(*current).at(address[1]);++r.native_commands.at(command);
    if(io_direction=='R')++r.io_reads;
    if(io_direction=='W')++r.io_writes;
    const auto type=classes.at(command);
    const auto& expansion=device->m_spec->command_expansions.at(command);
    if(type!=Other && !(type==ActAll&&!expansion.empty()))
      targets(command,address,mask,[&](int bank){apply(type,bank,now,command);});
    for(const auto& p:expansion) {
      auto target=address;
      for(const auto& [level,value]:p.address_overrides)target[level]=value;
      targets(p.command,target,0,[&](int bank) {
        // A primitive timestamp can be later than the next external command.
        pending.push({now+p.offset,sequence++,bank,classes.at(p.command),p.command,0,false});
      });
    }
    advance(now); // Apply offset-zero primitives before another same-CK issue.
  }

  void set_stage(Time now,int id) {
    advance(now);flush(now);current=&stage(id);
  }
  void finish(Time now) {advance(now);flush(now);elapsed=now;}

  void write(std::ostream& out,int channel) const {
    out<<"{\"channel\":"<<channel<<",\"elapsed_ck\":"<<elapsed<<",\"pending_after_end\":"<<pending.size()<<",\"banks\":[";
    for(int i=0;i<32;++i) {
      const auto& b=banks[i];if(i)out<<',';
      out<<"{\"rank\":"<<i/16<<",\"bank\":"<<i%16<<",\"reads\":"<<b.reads<<",\"writes\":"<<b.writes
         <<",\"activations\":"<<b.activations<<",\"precharges\":"<<b.precharges<<",\"REFpb\":"<<b.refpb
         <<",\"REFab\":"<<b.refab<<",\"state_ck\":";array(out,b.cycles);out<<'}';
    }
    out<<"],\"stages\":[";bool comma=false;
    for(const auto& [id,s]:stages)for(int rank=0;rank<2;++rank) {
      if(comma)out<<',';
      comma=true;const auto& r=s[rank];
      out<<"{\"stage_id\":"<<id<<",\"rank\":"<<rank<<",\"reads\":"<<r.reads<<",\"writes\":"<<r.writes
         <<",\"activations\":"<<r.activations<<",\"precharges\":"<<r.precharges
         <<",\"REFpb_bank_events\":"<<r.refpb_banks<<",\"REFab_bank_events\":"<<r.refab_banks
         <<",\"io_reads\":"<<r.io_reads<<",\"io_writes\":"<<r.io_writes<<",\"state_ck\":";array(out,r.bank_cycles);
      out<<",\"active_banks_ck\":";array(out,r.active_banks_ck);
      out<<",\"refresh_banks_ck\":";array(out,r.refresh_banks_ck);
      out<<",\"active_or_refresh_banks_ck\":";array(out,r.active_or_refresh_banks_ck);
      out<<",\"native_commands\":";array(out,r.native_commands);
      out<<",\"primitive_commands\":";array(out,r.primitive_commands);out<<'}';
    }
    out<<"]}";
  }

 private:
  enum Kind {Other,Act1,Act2,ActAll,Pre,RefPerBank,RefAllBank,Read,Write};
  struct Event {
    Time at;uint64_t order;int bank;Kind kind;int command;uint64_t generation;bool end;
    bool operator>(const Event& x)const {return at!=x.at?at>x.at:order>x.order;}
  };
  std::vector<Kind> classes;
  Stage* current=nullptr;
  std::priority_queue<Event,std::vector<Event>,std::greater<Event>> pending;
  std::array<Time,2> rank_since{};
  std::array<int,2> active{},refresh{};
  Time observed=0;
  uint64_t sequence=0;

  Stage& stage(int id) {
    auto [it,inserted]=stages.try_emplace(id);
    if(inserted)for(auto& r:it->second) {
      r.native_commands.resize(classes.size());r.primitive_commands.resize(classes.size());
    }
    return it->second;
  }
  static bool is_active(State s) {return s==Activating||s==Active;}
  void rank_account(int rank,Time now) {
    if(now<rank_since[rank])throw std::runtime_error("power rank clock reversed");
    auto dt=now-rank_since[rank];auto& r=(*current)[rank];
    r.active_banks_ck.at(active[rank])+=dt;r.refresh_banks_ck.at(refresh[rank])+=dt;
    r.active_or_refresh_banks_ck.at(active[rank]+refresh[rank])+=dt;rank_since[rank]=now;
  }
  void bank_account(int id,Time now) {
    auto& b=banks[id];if(now<b.since)throw std::runtime_error("power bank clock reversed");
    const auto dt=now-b.since;b.cycles[b.state]+=dt;(*current)[id/16].bank_cycles[b.state]+=dt;b.since=now;
  }
  void change(int id,State state,Time now) {
    auto& b=banks[id];const int rank=id/16;bank_account(id,now);rank_account(rank,now);
    active[rank]+=int(is_active(state))-int(is_active(b.state));
    refresh[rank]+=int(state==Refreshing)-int(b.state==Refreshing);
    b.state=state;++b.generation;
  }
  template<class F>void targets(int cmd,const Ramulator::AddrVec_t& a,uint16_t mask,F f) {
    device->for_each_target_bank_while(cmd,a,[&](int bank){f(bank);return true;},mask);
  }
  void apply(Kind type,int id,Time now,int command) {
    auto& b=banks[id];auto& r=(*current)[id/16];
    if(type==Read) {++b.reads;++r.reads;return;}
    if(type==Write) {++b.writes;++r.writes;return;}
    if(type==Act1) {change(id,Activating,now);return;}
    if(type==Act2||type==ActAll) {
      if(b.state==Active||b.state==Refreshing)throw std::runtime_error("power activation on open/refreshing bank");
      ++b.activations;++r.activations;change(id,Active,now);return;
    }
    if(type==Pre) {
      if(is_active(b.state)) {++b.precharges;++r.precharges;}
      if(b.state!=Precharged) {
        change(id,Precharging,now);
        const auto& name=device->m_spec->command_names[command];
        auto recovery=device->m_spec->get_timing_value(name.starts_with("PREab")?"nRPab":"nRP");
        pending.push({now+recovery,sequence++,id,Other,-1,b.generation,true});
      }
      return;
    }
    if(type==RefPerBank||type==RefAllBank) {
      if(type==RefPerBank){++b.refpb;++r.refpb_banks;}else{++b.refab;++r.refab_banks;}
      if(is_active(b.state)||b.state==Refreshing)throw std::runtime_error("power refresh on busy bank");
      change(id,Refreshing,now);
      const auto recovery=device->m_spec->get_timing_value(type==RefPerBank?"nRFCpb":"nRFC");
      pending.push({now+recovery,sequence++,id,Other,-1,b.generation,true});
    }
  }
  void advance(Time now) {
    if(now<observed)throw std::runtime_error("power observation clock reversed");
    while(!pending.empty()&&pending.top().at<=now) {
      const auto e=pending.top();pending.pop();
      if(e.end) {if(banks[e.bank].generation==e.generation)change(e.bank,Precharged,e.at);}
      else {++(*current)[e.bank/16].primitive_commands[e.command];apply(e.kind,e.bank,e.at,e.command);}
    }
    observed=now;
  }
  void flush(Time now) {for(int i=0;i<32;++i)bank_account(i,now);for(int r=0;r<2;++r)rank_account(r,now);}
  template<class T>static void array(std::ostream& out,const T& values) {
    out<<'[';bool comma=false;for(auto v:values){if(comma)out<<',';comma=true;out<<v;}out<<']';
  }
};
}
