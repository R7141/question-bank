<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ArrowLeft, ArrowRight, Network, Pencil, Plus, Trash2, X } from '@lucide/vue'
import { toast } from 'vue-sonner'
import type {
  KnowledgePoint,
  KnowledgeRelationDetail,
  KnowledgeRelationType,
} from '@/types'

const props = defineProps<{
  open: boolean
  point: KnowledgePoint | null
  knowledgePoints: KnowledgePoint[]
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const { $api } = useNuxtApp()

const isOpen = computed({
  get: () => props.open,
  set: (value) => emit('update:open', value),
})

const relations = ref<KnowledgeRelationDetail[]>([])
const relationTypes = ref<KnowledgeRelationType[]>([])
const filterTypeId = ref('all')
const loading = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  targetId: '',
  relationTypeId: '',
  description: '',
})

const selectablePoints = computed(() =>
  props.knowledgePoints.filter(
    (kp) => !kp.is_category && kp.id !== props.point?.id
  )
)

const activeRelationTypes = computed(() =>
  relationTypes.value.filter((t) => t.is_active)
)

const filteredRelations = computed(() => {
  if (filterTypeId.value === 'all') return relations.value
  return relations.value.filter(
    (r) => String(r.relation_type_id) === filterTypeId.value
  )
})

const pointName = (id: number) =>
  props.knowledgePoints.find((kp) => kp.id === id)?.name ?? `#${id}`

const isOutgoing = (relation: KnowledgeRelationDetail) =>
  relation.source_id === props.point?.id

const typeName = (relation: KnowledgeRelationDetail) =>
  relation.relation_type?.name ??
  relationTypes.value.find((t) => t.id === relation.relation_type_id)?.name ??
  '关系'

const strength = (relation: KnowledgeRelationDetail) => {
  const value = relation.attributes?.strength
  return typeof value === 'string' ? value : null
}

const directionLabel = (relation: KnowledgeRelationDetail) => {
  if (relation.relation_type?.code === 'prerequisite') {
    return isOutgoing(relation) ? '当前为先修' : '当前为后继'
  }
  return isOutgoing(relation) ? '出' : '入'
}

const resetForm = () => {
  editingId.value = null
  form.targetId = ''
  form.relationTypeId = activeRelationTypes.value[0]
    ? String(activeRelationTypes.value[0].id)
    : ''
  form.description = ''
}

const fetchData = async () => {
  if (!props.point) return
  loading.value = true
  try {
    const [relationRows, typeRows] = await Promise.all([
      $api<KnowledgeRelationDetail[]>(
        `/knowledge-points/${props.point.id}/relations`,
        { query: { direction: 'both', limit: 200 } }
      ),
      $api<KnowledgeRelationType[]>('/knowledge-relation-types'),
    ])
    relations.value = relationRows
    relationTypes.value = typeRows
    if (!form.relationTypeId && typeRows.length > 0) {
      form.relationTypeId = String(typeRows.find((t) => t.is_active)?.id ?? typeRows[0].id)
    }
  } catch (error: any) {
    toast.error('加载关系失败: ' + (error.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.point?.id],
  ([open]) => {
    if (open) {
      resetForm()
      fetchData()
    }
  },
  { immediate: true }
)

const startEdit = (relation: KnowledgeRelationDetail) => {
  editingId.value = relation.id
  form.targetId = String(isOutgoing(relation) ? relation.target_id : relation.source_id)
  form.relationTypeId = String(relation.relation_type_id)
  form.description = relation.description ?? ''
}

const submit = async () => {
  if (!props.point) return
  if (!editingId.value && !form.targetId) {
    toast.error('请选择目标知识点')
    return
  }
  if (!form.relationTypeId) {
    toast.error('请选择关系类型')
    return
  }

  saving.value = true
  try {
    if (editingId.value) {
      await $api(`/knowledge-relations/${editingId.value}`, {
        method: 'PUT',
        body: {
          relation_type_id: Number(form.relationTypeId),
          description: form.description || null,
        },
      })
      toast.success('关系已更新')
    } else {
      await $api('/knowledge-relations', {
        method: 'POST',
        body: {
          source_id: props.point.id,
          target_id: Number(form.targetId),
          relation_type_id: Number(form.relationTypeId),
          description: form.description || null,
          source: 'manual',
          status: 'verified',
        },
      })
      toast.success('关系已创建')
    }
    resetForm()
    await fetchData()
  } catch (error: any) {
    toast.error('保存失败: ' + (error.data?.detail || error.message))
  } finally {
    saving.value = false
  }
}

const remove = async (relation: KnowledgeRelationDetail) => {
  if (!confirm('确定删除这条知识关系吗？')) return
  try {
    await $api(`/knowledge-relations/${relation.id}`, { method: 'DELETE' })
    toast.success('关系已删除')
    if (editingId.value === relation.id) resetForm()
    await fetchData()
  } catch (error: any) {
    toast.error('删除失败: ' + (error.data?.detail || error.message))
  }
}
</script>

<template>
  <Sheet v-model:open="isOpen">
    <SheetContent class="w-[560px] sm:w-[680px] overflow-y-auto">
      <SheetHeader>
        <SheetTitle class="flex items-center gap-2">
          <Network class="h-4 w-4" />
          知识关系
        </SheetTitle>
        <SheetDescription>
          {{ point?.name }} · 管理先修、关联等语义关系
        </SheetDescription>
      </SheetHeader>

      <div class="mt-6 space-y-6">
        <div class="rounded-lg border p-4 space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-medium">
              {{ editingId ? '编辑关系' : '新增关系' }}
            </h3>
            <Button
              v-if="editingId"
              variant="ghost"
              size="sm"
              @click="resetForm"
            >
              <X class="mr-1 h-3.5 w-3.5" />取消编辑
            </Button>
          </div>

          <div class="grid gap-3 sm:grid-cols-2">
            <div class="space-y-1">
              <label class="text-xs text-muted-foreground">关系类型</label>
              <Select v-model="form.relationTypeId">
                <SelectTrigger>
                  <SelectValue placeholder="选择关系类型" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="type in activeRelationTypes"
                    :key="type.id"
                    :value="String(type.id)"
                  >
                    {{ type.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="space-y-1">
              <label class="text-xs text-muted-foreground">目标知识点</label>
              <Select v-model="form.targetId" :disabled="!!editingId">
                <SelectTrigger>
                  <SelectValue placeholder="选择目标知识点" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="kp in selectablePoints"
                    :key="kp.id"
                    :value="String(kp.id)"
                  >
                    {{ kp.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-xs text-muted-foreground">说明（可选）</label>
            <Textarea
              v-model="form.description"
              rows="2"
              placeholder="为什么存在这条关系"
            />
          </div>

          <div class="flex justify-end">
            <Button size="sm" :disabled="saving" @click="submit">
              <Plus v-if="!editingId" class="mr-1 h-3.5 w-3.5" />
              {{ editingId ? '保存修改' : '添加关系' }}
            </Button>
          </div>
        </div>

        <div class="space-y-3">
          <div class="flex items-center justify-between gap-2">
            <h3 class="text-sm font-medium">
              已有关系
              <span class="ml-1 text-xs text-muted-foreground">
                {{ filteredRelations.length }}
              </span>
            </h3>
            <Select v-model="filterTypeId">
              <SelectTrigger class="h-8 w-36">
                <SelectValue placeholder="全部类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部类型</SelectItem>
                <SelectItem
                  v-for="type in relationTypes"
                  :key="type.id"
                  :value="String(type.id)"
                >
                  {{ type.name }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div v-if="loading" class="py-8 text-center text-sm text-muted-foreground">
            加载中...
          </div>
          <div
            v-else-if="filteredRelations.length === 0"
            class="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground"
          >
            暂无知识关系
          </div>

          <div v-else class="space-y-2">
            <div
              v-for="relation in filteredRelations"
              :key="relation.id"
              class="rounded-lg border p-3 text-sm"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <Badge variant="secondary">{{ typeName(relation) }}</Badge>
                    <Badge variant="outline" class="text-[10px]">
                      {{ directionLabel(relation) }}
                    </Badge>
                    <Badge
                      v-if="strength(relation)"
                      variant="outline"
                      class="text-[10px]"
                    >
                      {{ strength(relation) }}
                    </Badge>
                    <Badge
                      v-if="relation.status !== 'verified'"
                      variant="outline"
                      class="text-[10px]"
                    >
                      {{ relation.status }}
                    </Badge>
                  </div>
                  <div class="mt-1.5 flex items-center gap-1.5 text-muted-foreground">
                    <ArrowRight v-if="isOutgoing(relation)" class="h-3.5 w-3.5" />
                    <ArrowLeft v-else class="h-3.5 w-3.5" />
                    <span class="font-medium text-foreground">
                      {{ pointName(isOutgoing(relation) ? relation.target_id : relation.source_id) }}
                    </span>
                  </div>
                  <p v-if="relation.description" class="mt-1 text-xs text-muted-foreground">
                    {{ relation.description }}
                  </p>
                </div>
                <div class="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-7 w-7"
                    title="编辑"
                    @click="startEdit(relation)"
                  >
                    <Pencil class="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-7 w-7 text-destructive"
                    title="删除"
                    @click="remove(relation)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </SheetContent>
  </Sheet>
</template>
