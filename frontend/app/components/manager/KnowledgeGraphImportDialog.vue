<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertTriangle,
  CheckCircle2,
  FileArchive,
  Loader2,
  Upload,
  X,
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { toast } from 'vue-sonner'
import type {
  ImportAction,
  KnowledgeImportPreview,
  KnowledgeImportResult,
} from '@/types'

const props = defineProps<{
  open: boolean
  subjectId: number | null
  subjectName: string
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'imported'): void
}>()

const { $api } = useNuxtApp()

const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)
const preview = ref<KnowledgeImportPreview | null>(null)
const result = ref<KnowledgeImportResult | null>(null)
const loadingPreview = ref(false)
const applying = ref(false)
const updateExisting = ref(false)
const error = ref<string | null>(null)

const actionLabels: Record<ImportAction['action'], string> = {
  create: '新增',
  link: '关联',
  update: '更新',
  skip: '跳过',
  conflict: '冲突',
}

const actionVariants: Record<ImportAction['action'], 'default' | 'secondary' | 'outline' | 'destructive'> = {
  create: 'default',
  link: 'secondary',
  update: 'outline',
  skip: 'outline',
  conflict: 'destructive',
}

const actionRows = computed(() => preview.value?.actions ?? [])
const visibleActions = computed(() => actionRows.value.slice(0, 200))

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      selectedFile.value = null
      preview.value = null
      result.value = null
      updateExisting.value = false
      error.value = null
      loadingPreview.value = false
      applying.value = false
    }
  }
)

const close = () => emit('update:open', false)

const triggerFileInput = () => fileInput.value?.click()

const handleFileChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    toast.error('请上传 .zip 文件')
    return
  }
  if (file.size > 50 * 1024 * 1024) {
    toast.error('文件过大，请确保小于 50MB')
    return
  }
  selectedFile.value = file
  preview.value = null
  result.value = null
  error.value = null
}

const clearFile = () => {
  selectedFile.value = null
  preview.value = null
  result.value = null
  error.value = null
  if (fileInput.value) fileInput.value.value = ''
}

const buildFormData = () => {
  if (!selectedFile.value || !props.subjectId) return null
  const formData = new FormData()
  formData.append('file', selectedFile.value)
  formData.append('subject_id', String(props.subjectId))
  formData.append('update_existing', String(updateExisting.value))
  return formData
}

const runPreview = async () => {
  const formData = buildFormData()
  if (!formData) return
  loadingPreview.value = true
  error.value = null
  result.value = null
  try {
    preview.value = await $api<KnowledgeImportPreview>(
      '/knowledge-points/import-external/preview',
      { method: 'POST', body: formData }
    )
  } catch (e: any) {
    error.value = e.data?.detail || e.message || '预览失败'
  } finally {
    loadingPreview.value = false
  }
}

const runApply = async () => {
  const formData = buildFormData()
  if (!formData || !preview.value) return
  formData.append('checksum', preview.value.checksum)
  applying.value = true
  error.value = null
  try {
    result.value = await $api<KnowledgeImportResult>(
      '/knowledge-points/import-external',
      { method: 'POST', body: formData }
    )
    toast.success('知识图谱导入完成')
    emit('imported')
  } catch (e: any) {
    error.value = e.data?.detail || e.message || '导入失败'
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="w-[95vw] sm:max-w-[760px] max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>外部知识图谱导入</DialogTitle>
        <DialogDescription>
          从 cn-math-taxonomy 的 zip 中导入数学知识图谱到「{{ subjectName }}」。
        </DialogDescription>
      </DialogHeader>

      <Alert>
        <AlertTriangle class="h-4 w-4" />
        <AlertTitle>数据许可与来源</AlertTitle>
        <AlertDescription>
          数据来源：cn-math-taxonomy，许可协议 CC BY-NC 4.0（非商业使用，需署名）。
          请确认你的使用场景符合该许可。数据不会提交到 QB 仓库。
        </AlertDescription>
      </Alert>

      <div class="space-y-4">
        <div class="space-y-2">
          <Label>1. 选择包含 topics.json 与 dependencies.json 的 zip</Label>
          <input
            ref="fileInput"
            type="file"
            accept=".zip,application/zip"
            class="hidden"
            @change="handleFileChange"
          />
          <div
            v-if="!selectedFile"
            class="rounded-lg border-2 border-dashed p-6 text-center cursor-pointer hover:border-primary/50"
            role="button"
            tabindex="0"
            @click="triggerFileInput"
            @keydown.enter="triggerFileInput"
          >
            <Upload class="mx-auto mb-2 h-7 w-7 text-muted-foreground" />
            <p class="text-sm font-medium">点击选择 zip 文件</p>
            <p class="mt-1 text-xs text-muted-foreground">
              支持仓库 data/ 目录下的 topics.json / dependencies.json
            </p>
          </div>
          <div v-else class="flex items-center gap-3 rounded-lg border p-3">
            <FileArchive class="h-8 w-8 shrink-0 text-primary" />
            <div class="min-w-0 flex-1 text-sm">
              <p class="truncate font-medium">{{ selectedFile.name }}</p>
              <p class="text-xs text-muted-foreground">{{ formatSize(selectedFile.size) }}</p>
            </div>
            <Button variant="ghost" size="icon" @click="clearFile">
              <X class="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <Checkbox
            id="update-existing"
            :model-value="updateExisting"
            @update:model-value="(value) => updateExisting = value as boolean"
          />
          <Label for="update-existing" class="text-sm font-normal">
            允许用外部数据更新已存在知识点的描述等字段
          </Label>
        </div>

        <div v-if="error" class="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {{ error }}
        </div>

        <div v-if="preview" class="space-y-4">
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div class="rounded-lg border p-3">
              <p class="text-xs text-muted-foreground">节点</p>
              <p class="text-lg font-semibold">{{ preview.total_nodes }}</p>
            </div>
            <div class="rounded-lg border p-3">
              <p class="text-xs text-muted-foreground">新增</p>
              <p class="text-lg font-semibold">{{ preview.to_create }}</p>
            </div>
            <div class="rounded-lg border p-3">
              <p class="text-xs text-muted-foreground">关联/更新</p>
              <p class="text-lg font-semibold">{{ preview.to_link + preview.to_update }}</p>
            </div>
            <div class="rounded-lg border p-3">
              <p class="text-xs text-muted-foreground">关系</p>
              <p class="text-lg font-semibold">{{ preview.relations_to_create }}</p>
            </div>
          </div>

          <div v-if="preview.conflicts > 0" class="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
            检测到 {{ preview.conflicts }} 个冲突，需先处理同名节点后才能导入。
          </div>
          <ul v-if="preview.errors.length" class="list-disc space-y-1 pl-5 text-xs text-destructive">
            <li v-for="message in preview.errors.slice(0, 20)" :key="message">{{ message }}</li>
          </ul>

          <div class="max-h-64 overflow-y-auto rounded-lg border">
            <table class="w-full text-xs">
              <thead class="sticky top-0 bg-muted/80">
                <tr>
                  <th class="p-2 text-left font-medium">动作</th>
                  <th class="p-2 text-left font-medium">节点</th>
                  <th class="p-2 text-left font-medium">类型</th>
                  <th class="p-2 text-left font-medium">外部 ID</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="action in visibleActions" :key="`${action.external_id}-${action.name}`" class="border-t">
                  <td class="p-2">
                    <Badge :variant="actionVariants[action.action]">
                      {{ actionLabels[action.action] }}
                    </Badge>
                  </td>
                  <td class="p-2">{{ action.name }}</td>
                  <td class="p-2 text-muted-foreground">{{ action.node_type }}</td>
                  <td class="p-2 text-muted-foreground">{{ action.external_id }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="actionRows.length > visibleActions.length" class="text-xs text-muted-foreground">
            仅显示前 {{ visibleActions.length }} 条，共 {{ actionRows.length }} 条。
          </p>
        </div>

        <div v-if="result" class="rounded-lg border p-4 space-y-2">
          <div class="flex items-center gap-2 text-sm font-medium">
            <CheckCircle2 class="h-4 w-4 text-green-600" />
            导入完成
          </div>
          <div class="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <span>新增节点：{{ result.created_nodes }}</span>
            <span>关联节点：{{ result.linked_nodes }}</span>
            <span>更新节点：{{ result.updated_nodes }}</span>
            <span>新增关系：{{ result.created_relations }}</span>
            <span>跳过关系：{{ result.skipped_relations }}</span>
            <span>耗时：{{ result.duration }}s</span>
            <span>向量同步：{{ result.vector_synced ? '是' : '否' }}</span>
          </div>
          <ul v-if="result.errors.length" class="list-disc space-y-1 pl-5 text-xs text-destructive">
            <li v-for="message in result.errors" :key="message">{{ message }}</li>
          </ul>
        </div>
      </div>

      <DialogFooter class="gap-2">
        <Button variant="outline" @click="close">关闭</Button>
        <Button
          variant="outline"
          :disabled="!selectedFile || loadingPreview || applying"
          @click="runPreview"
        >
          <Loader2 v-if="loadingPreview" class="mr-2 h-4 w-4 animate-spin" />
          预览
        </Button>
        <Button
          :disabled="!preview || preview.conflicts > 0 || applying || !!result"
          @click="runApply"
        >
          <Loader2 v-if="applying" class="mr-2 h-4 w-4 animate-spin" />
          执行导入
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
