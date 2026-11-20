<script setup lang="ts">
import UiEmpty from '@/components/ui/UiEmpty.vue';
import UiTag from '@/components/ui/UiTag.vue';
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>审计</h1>
        <p class="page-head__meta">谁在什么时候、对哪个数据源、执行了什么</p>
      </div>
      <UiTag tone="neutral">P1 接通</UiTag>
    </header>

    <section class="panel">
      <UiEmpty
        title="审计流尚未接通"
        text="后端已经在记录登录、数据源增删、连通性探测与结构读取；列表接口和控制台将在 P1 一起开放。"
      />
    </section>

    <div class="facts">
      <div class="fact">
        <span class="fact__label">已记录</span>
        <span class="fact__value">登录 · 数据源增删改查 · 结构读取</span>
      </div>
      <div class="fact">
        <span class="fact__label">写入方式</span>
        <span class="fact__value">只追加，不提供修改与删除接口</span>
      </div>
      <div class="fact">
        <span class="fact__label">后续</span>
        <span class="fact__value">SQL 执行、生成失败与人工纠错都会进同一条流</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.facts {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-top: 20px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}

.fact {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 16px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
}

.fact:last-child {
  border-bottom: none;
}

.fact__label {
  color: var(--ink-3);
}

.fact__value {
  color: var(--ink-2);
}
</style>